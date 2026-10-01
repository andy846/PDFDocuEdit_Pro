"""Bounded page generation, subprocess assembly and reconciled publication."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

import fitz

from composition.data.source import RecordStore
from composition.engine.assets import qpdf_executable
from composition.engine.fonts import RecordFontError
from composition.engine.renderer import Renderer
from composition.engine.rules import RecordRuleError
from composition.template.model import CompositionError, Template, required_fields
from composition.template.serializer import file_hash
from core.pdf_io import validate_pdf_file

from .model import JobResult, ProductionJob, now
from .resources import peak_memory


class JobCancelled(CompositionError):
    pass


def check_cancel(is_cancelled):
    if is_cancelled and is_cancelled():
        raise JobCancelled("Production cancelled.")


def reconcile(result: JobResult) -> None:
    if not (
        result.input_records == result.processed_records == result.successful_records
        and result.failed_records == 0
        and result.pages_per_record >= 1
        and result.expected_pages == result.input_records * result.pages_per_record
        and result.generated_pages == result.expected_pages
        and result.generated_files == 1
        and (not result.rule_summary or (result.rule_summary.get("complete") is True
             and result.rule_summary.get("records_checked") == result.input_records))
    ):
        raise CompositionError(
            "RECONCILIATION FAILED: "
            f"input={result.input_records}, processed={result.processed_records}, "
            f"successful={result.successful_records}, failed={result.failed_records}, "
            f"pages={result.generated_pages}, expected_pages={result.expected_pages}, files={result.generated_files}."
        )


def _assemble(chunks: list[Path], output: Path, executable: Path, is_cancelled) -> int:
    arguments = output.parent / "assembly.args"
    # qpdf argument files accept one complete argument per line, including spaces.
    lines = ["--empty", "--pages", *(str(path) for path in chunks), "--", str(output)]
    if any("\n" in value or "\r" in value for value in lines):
        raise CompositionError("Output paths may not contain line breaks.")
    arguments.write_text("\n".join(lines) + "\n", encoding="utf-8")
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    process = subprocess.Popen(
        [str(executable), "@" + str(arguments)], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, **options,
    )
    try:
        while True:
            check_cancel(is_cancelled)
            try:
                stdout, stderr = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode:
            message = (stderr or stdout).decode("utf-8", errors="replace")[-4000:]
            raise CompositionError(f"qpdf assembly failed ({process.returncode}): {message}")
        return peak_memory(process)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()
        arguments.unlink(missing_ok=True)


def _csv_value(value):
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _write_reports(directory: Path, result: JobResult, template: Template, store: RecordStore | None) -> None:
    log = {
        "job_version": 2,
        **result.to_dict(),
        "template_name": template.name,
        "template_sha256": hashlib.sha256(
            json.dumps(template.to_dict(), sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
        "source": store.metadata["source"] if store else None,
        "record_identity": "source_sha256 + one-based imported record ordinal",
        "page_mapping": {
            "type": "fixed_pages", "pages_per_record": len(template.pages),
            "formula": "output page = (record ordinal - 1) * pages_per_record + template page ordinal",
            "template_pages": [{"ordinal": i+1, "id": p.id, "name": p.name}
                               for i, p in enumerate(template.pages)],
        },
    }
    (directory / "job.json").write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    columns = {
        "Job ID": result.job_id, "Source File": store.metadata["source"]["path"] if store else "",
        "Template Name": template.name, "Start Time": result.started_at, "End Time": result.finished_at,
        "Input Records": result.input_records, "Processed Records": result.processed_records,
        "Successful Records": result.successful_records, "Failed Records": result.failed_records,
        "Pages Per Record": result.pages_per_record, "Expected Pages": result.expected_pages,
        "Page Count": result.generated_pages, "Output Files": result.generated_files,
        "Output File": result.output_pdf, "File Size": result.output_size,
        "Repaired Glyphs": result.repaired_glyphs, "Repaired Records": result.repaired_records,
        "Glyph Repair Report": result.glyph_repair_report,
        "Conditional Objects": result.rule_summary.get("configured_objects", 0),
        "Rules Checked Records": result.rule_summary.get("records_checked", 0),
        "Rules Check Complete": result.rule_summary.get("complete", False),
        "Hidden Object Occurrences": result.rule_summary.get("hidden_occurrences", 0),
        "Alternate Content Occurrences": result.rule_summary.get("alternate_occurrences", 0),
        "Status": result.status, "Error Record": result.error_record or "", "Error": result.error,
    }
    with (directory / "control.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns.keys())
        writer.writerow([_csv_value(value) for value in columns.values()])


def generate(
    job: ProductionJob, *, progress: Callable | None = None, is_cancelled: Callable | None = None,
) -> JobResult:
    """Compose a disk-backed imported snapshot without loading all rendered pages."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", job.job_id):
        raise CompositionError("Invalid job identity.")
    if not 1 <= job.chunk_size <= 1000:
        raise CompositionError("Chunk size must be between 1 and 1,000 pages.")
    template = Template.from_dict(job.template)
    output_root = Path(job.output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    final = output_root / job.job_id
    if final.exists() or (output_root / f"{job.job_id}-failed").exists():
        raise CompositionError("That production job already exists. Use a new job ID.")
    staging = Path(tempfile.mkdtemp(prefix=f".{job.job_id}-", dir=output_root))
    result = JobResult(job.job_id, pages_per_record=len(template.pages))
    store = None
    current_record = None
    chunk = None
    chunks = []
    try:
        check_cancel(is_cancelled)
        store = RecordStore(job.record_store)
        result.input_records = store.count
        result.expected_pages = store.count * len(template.pages)
        missing = required_fields(template) - set(store.fields)
        if missing:
            raise CompositionError(f"Missing mapped fields: {', '.join(sorted(missing))}")
        executable = qpdf_executable()
        assets = [page.background for page in template.pages] + [
            value for element in template.all_elements() for value in (element.image, element.rules.alternative.image if element.rules.alternative else "", element.font.file,
                          *(spec.file for spec in element.glyph_repairs.values())) if value
        ]
        fingerprints = {path: file_hash(Path(path)) for path in assets if path}
        with tempfile.TemporaryDirectory(prefix="font-subsets-", dir=staging) as font_folder, Renderer(template) as renderer:
            if progress:
                progress(0, 0, "Preparing exact font subsets")
            repair_audit = staging / "glyph-repairs-preflight.csv"
            try:
                renderer.prepare_fonts(store.records(), font_folder, progress, is_cancelled, audit_path=repair_audit)
            finally:
                result.rule_summary = dict(renderer.rule_summary)
            repair_summary = dict(renderer.repair_summary)
            check_cancel(is_cancelled)
            chunk = fitz.open()
            for ordinal, record in store.records():
                check_cancel(is_cancelled)
                current_record = ordinal
                try:
                    renderer.render(chunk, record, ordinal, is_cancelled=is_cancelled)
                except Exception:
                    if is_cancelled and is_cancelled():
                        raise JobCancelled("Production cancelled between template pages.") from None
                    result.failed_records += 1
                    result.processed_records += 1
                    result.error_record = ordinal
                    raise
                result.processed_records += 1
                result.successful_records += 1
                if chunk.page_count >= job.chunk_size or ordinal == store.count:
                    check_cancel(is_cancelled)
                    renderer.finalize(chunk)
                    path = staging / f"chunk-{len(chunks):06}.pdf"
                    chunk.save(path, deflate=True, garbage=1)
                    result.generated_pages += chunk.page_count
                    chunk.close()
                    chunk = fitz.open()
                    chunks.append(path)
                if progress and (ordinal % 25 == 0 or ordinal == store.count):
                    progress(ordinal, store.count, f"Composing record {ordinal:,} / {store.count:,}")
            chunk.close()
            chunk = None
        check_cancel(is_cancelled)
        for path, digest in fingerprints.items():
            if file_hash(Path(path)) != digest:
                raise CompositionError("A template asset changed during production. Run the job again.")
        if progress:
            progress(store.count, store.count, "Assembling and validating production PDF")
        pdf = staging / "production.pdf"
        result.assembler_peak_memory_bytes = _assemble(chunks, pdf, executable, is_cancelled)
        for path in chunks:
            path.unlink()
        check_cancel(is_cancelled)
        validate_pdf_file(pdf, expected_page_count=result.expected_pages)
        with fitz.open(pdf) as checked:
            result.generated_pages = checked.page_count
        result.generated_files = 1
        reconcile(result)
        if repair_summary["occurrences"]:
            repair_audit.rename(staging / "glyph-repairs.csv")
            result.repaired_glyphs = repair_summary["occurrences"]
            result.repaired_records = repair_summary["records"]
            result.glyph_repair_report = str(final / "glyph-repairs.csv")
            result.warnings.append(
                f"Explicit glyph repairs: {result.repaired_glyphs} occurrence(s) in {result.repaired_records} record(s). "
                "Primary fonts retained; review glyph-repairs.csv.")
        else:
            repair_audit.unlink(missing_ok=True)
        result.output_size = pdf.stat().st_size
        result.output_pdf = str(final / pdf.name)
        result.report_dir = str(final)
        result.composer_peak_memory_bytes = peak_memory()
        result.status = "completed"
        result.finished_at = now()
        _write_reports(staging, result, template, store)
        check_cancel(is_cancelled)
        # A unique, same-parent directory rename publishes the PDF and both reports together.
        os.rename(staging, final)
        return result
    except Exception as exc:
        if chunk is not None:
            chunk.close()
            chunk = None
        was_cancelled = isinstance(exc, JobCancelled) or (is_cancelled is not None and is_cancelled())
        result.status = "cancelled" if was_cancelled else "failed"
        result.error = str(exc)
        if isinstance(exc, RecordFontError):
            result.error_record = exc.record_ordinal
            result.failed_records = 1
            result.processed_records = 1
            result.warnings.append(
                "Font validation failed before page composition. No records were composed. "
                "Select the reported object and configure an explicit repair for the missing code point. "
                "Keep the required primary font; review any private-use glyph against its source."
            )
        if isinstance(exc, RecordRuleError):
            result.error_record = exc.record_ordinal
            result.failed_records = result.processed_records = 1
            result.warnings.append("Rule validation failed before composition. Review the reported condition; no records composed.")
        result.finished_at = now()
        result.output_pdf = ""
        result.output_size = 0
        result.generated_files = 0
        if result.error_record is None and current_record is not None and result.failed_records:
            result.error_record = current_record
        # Keep only diagnostics; incomplete PDFs are never published.
        for path in staging.glob("*.pdf"):
            path.unlink(missing_ok=True)
        failure_dir = output_root / f"{job.job_id}-failed"
        result.report_dir = str(failure_dir)
        try:
            _write_reports(staging, result, template, store)
            os.rename(staging, failure_dir)
        except OSError as report_error:
            result.report_dir = ""
            result.warnings.append(f"Unable to publish diagnostic reports: {report_error}")
        return result
    finally:
        if staging.exists():
            resolved = staging.resolve()
            if resolved.parent != output_root or not resolved.name.startswith(f".{job.job_id}-"):
                raise CompositionError("Unsafe staging cleanup path.")
            shutil.rmtree(resolved)
