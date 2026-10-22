"""Analyze / review / repair privately / validate / atomically publish a copy."""

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import fitz

from core.io_atomic import atomic_output
from core.pdf_io import validate_pdf_file
from core.pdf_operations.analysis import check_cancel, file_hash, open_pdf, structure_check

from .inventory import analyze
from .matching import evaluate_sources
from .model import FontPreflightError, FontRepairPlan
from .validation import compare_objects, compare_pages, digest, font_program, verify_reference


def prepare_repair(
    source,
    selections,
    reference,
    *,
    authorized_reference=False,
    password="",
    policy="print",
    is_cancelled=None,
):
    inventory = analyze(source, password=password, policy=policy, is_cancelled=is_cancelled)
    matches = evaluate_sources(source, inventory, selections, password=password, is_cancelled=is_cancelled)
    if inventory.protected or not inventory.complete:
        raise FontPreflightError("Signed/encrypted/restricted or incompletely analyzed PDFs are scan-only.")
    if not matches or any(m.status != "CANDIDATE_FOUND" for m in matches):
        raise FontPreflightError(
            "Every required unembedded resource needs a verified eligible original font; inspect the match decisions."
        )
    if not authorized_reference or not reference:
        raise FontPreflightError(
            "A trusted original-font reference PDF and confirmation are required; a fallback render is insufficient."
        )
    reference_hash = file_hash(reference, is_cancelled)
    with open_pdf(source, password) as original, open_pdf(reference) as correct:
        if correct.is_repaired or correct._pdf_operation_encrypted:
            raise FontPreflightError("Reference must be a readable, unencrypted authoritative PDF.")
        verify_reference(original, correct, inventory.resources, matches, is_cancelled=is_cancelled)
    if (
        file_hash(source, is_cancelled) != inventory.source_sha256
        or file_hash(reference, is_cancelled) != reference_hash
    ):
        raise FontPreflightError("Source/reference changed. Analyze again.")
    return inventory, FontRepairPlan(inventory.source_sha256, reference_hash, tuple(matches))


def repair_copy(
    source,
    output,
    selections,
    reference,
    *,
    authorized_reference=False,
    password="",
    policy="print",
    progress=None,
    is_cancelled=None,
):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output == source or output == Path(reference or source).resolve() or output.exists():
        raise FontPreflightError(
            "Choose a new output; sources and existing destinations are never overwritten."
        )
    inventory, plan = prepare_repair(
        source,
        selections,
        reference,
        authorized_reference=authorized_reference,
        password=password,
        policy=policy,
        is_cancelled=is_cancelled,
    )
    check_cancel(is_cancelled)
    with TemporaryDirectory(prefix="font-verified-") as directory:
        baseline = Path(directory) / "source.pdf"
        trusted = Path(directory) / "reference.pdf"
        # Immutable per-job copies; originals may be open in another program.
        import shutil

        shutil.copyfile(source, baseline)
        shutil.copyfile(reference, trusted)
        if file_hash(baseline) != plan.source_sha256 or file_hash(trusted) != plan.reference_sha256:
            raise FontPreflightError("Source/reference changed before generation.")
        with atomic_output(output, overwrite=False) as staged:
            with open_pdf(baseline) as original:
                descriptors = set()
                for match in plan.matches:
                    check_cancel(is_cancelled)
                    candidate = match.source
                    if file_hash(candidate.path, is_cancelled) != candidate.sha256:
                        raise FontPreflightError("Approved font changed. Select and verify it again.")
                    resource = next(r for r in inventory.resources if r.xref == match.font_xref)
                    if resource.descriptor in descriptors:
                        raise FontPreflightError(
                            "Shared descriptors between font objects require separate feasibility evidence."
                        )
                    descriptors.add(resource.descriptor)
                    program = original.get_new_xref()
                    original.update_object(program, f"<< /Length1 {Path(candidate.path).stat().st_size} >>")
                    original.update_stream(program, Path(candidate.path).read_bytes(), compress=False)
                    original.xref_set_key(resource.descriptor, "FontFile2", f"{program} 0 R")
                original.save(staged, garbage=0, deflate=False, encryption=fitz.PDF_ENCRYPT_NONE)
            validate_pdf_file(staged, expected_page_count=inventory.page_count)
            independent = structure_check(staged, is_cancelled=is_cancelled)
            if independent["status"] != "OK":
                raise FontPreflightError("Independent qpdf validation did not pass; no output published.")
            rescanned = analyze(staged, policy=policy, is_cancelled=is_cancelled)
            if not rescanned.complete or any(
                r.status != "EMBEDDED"
                for r in rescanned.resources
                if r.xref in {m.font_xref for m in plan.matches}
            ):
                raise FontPreflightError("Output font inventory failed validation.")
            with open_pdf(baseline) as original, open_pdf(staged) as produced, open_pdf(trusted) as correct:
                for match in plan.matches:
                    from .inventory import object_value
                    from .syntax import Ref

                    resource = next(r for r in inventory.resources if r.xref == match.font_xref)
                    ref = object_value(produced, resource.descriptor).get("FontFile2")
                    if (
                        not isinstance(ref, Ref)
                        or digest(font_program(produced, ref.xref)) != match.source.sha256
                    ):
                        raise FontPreflightError("Published font program differs from approved binary.")
                compare_objects(original, produced, descriptors, is_cancelled=is_cancelled)
                evidence = compare_pages(correct, produced, progress=progress, is_cancelled=is_cancelled)
            if (
                file_hash(source, is_cancelled) != plan.source_sha256
                or file_hash(reference, is_cancelled) != plan.reference_sha256
            ):
                raise FontPreflightError("Source/reference changed during validation; output withheld.")
            for match in plan.matches:
                if file_hash(match.source.path, is_cancelled) != match.source.sha256:
                    raise FontPreflightError("Font source changed during validation; output withheld.")
            check_cancel(is_cancelled)
            output_hash = file_hash(staged, is_cancelled)
    return {
        "schema_version": 1,
        "status": "VALIDATED",
        "output_pdf": str(output),
        "input_sha256": plan.source_sha256,
        "reference_sha256": plan.reference_sha256,
        "output_sha256": output_hash,
        "policy": policy,
        "matches": [m.to_dict() for m in plan.matches],
        "changes": [{"font_xref": m.font_xref, "action": "attach_full_FontFile2"} for m in plan.matches],
        "validation": {"original_objects_preserved": True, "qpdf": independent["status"], "pages": evidence},
    }


def export_report(report, path):
    path = Path(path)
    with atomic_output(path, overwrite=False) as staged:
        if path.suffix.lower() == ".csv":
            with staged.open("w", encoding="utf-8-sig", newline="") as stream:
                base_writer = csv.writer(stream)

                class SafeCSV:
                    def writerow(self, values):
                        base_writer.writerow(
                            [
                                "'" + value
                                if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@"))
                                else value
                                for value in values
                            ]
                        )

                writer = SafeCSV()
                if "repairs" in report:
                    writer.writerow(["Font xref", "Status", "Original font SHA256", "Reason"])
                    for row in report["repairs"]:
                        writer.writerow(
                            [row["font_xref"], "VALIDATED", row["source"]["sha256"], row["reason"]]
                        )
                    return
                writer.writerow(["File index", "Font xref", "Name", "Type", "Status", "Pages", "Reason"])
                rows = [("", row) for row in report.get("resources", [])]
                if "inventory" in report:
                    rows = [("", row) for row in report["inventory"].get("resources", [])]
                for item in report.get("files", []):
                    rows.extend(
                        (item["file_index"], row) for row in item.get("inventory", {}).get("resources", [])
                    )
                    if not item.get("inventory"):
                        rows.append(
                            (
                                item["file_index"],
                                {
                                    "xref": "",
                                    "name": "",
                                    "subtype": "",
                                    "status": item["status"],
                                    "pages": [],
                                    "reason": item.get("reason", ""),
                                },
                            )
                        )
                for file_index, row in rows:
                    writer.writerow(
                        [
                            file_index,
                            row["xref"],
                            row["name"],
                            row["subtype"],
                            row["status"],
                            ",".join(map(str, row["pages"])),
                            row["reason"],
                        ]
                    )
        else:
            staged.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def analyze_batch(sources, *, policy="print", password="", progress=None, is_cancelled=None):
    if not 1 <= len(sources) <= 10000:
        raise FontPreflightError("Choose 1–10,000 PDFs.")
    results = []
    for index, source in enumerate(sources, 1):
        check_cancel(is_cancelled)
        try:
            report = analyze(source, policy=policy, password=password, is_cancelled=is_cancelled).to_dict()
            results.append(
                {
                    "file_index": index,
                    "status": "ANALYZED" if report["complete"] else "REVIEW_REQUIRED",
                    "inventory": report,
                }
            )
        except FontPreflightError as exc:
            results.append({"file_index": index, "status": "FAILED", "reason": str(exc)})
        except Exception:
            check_cancel(is_cancelled)
            results.append(
                {
                    "file_index": index,
                    "status": "FAILED",
                    "reason": "Unable to inspect this PDF; source retained.",
                }
            )
        if progress:
            progress(index, len(sources), f"Analyzed file {index}/{len(sources)}")
    return {
        "schema_version": 1,
        "status": "COMPLETED" if all(r["status"] == "ANALYZED" for r in results) else "NEEDS_REVIEW",
        "files": results,
    }


def repair_job(source, output_dir, selections, reference, **kwargs):
    """Publish PDF and audit together; failures have metadata-only audit records."""
    import os

    from composition.production.model import new_job_id
    from core.pdf_operations.analysis import PdfCancelled

    job_id = new_job_id()
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    final = root / ("font-" + job_id)
    try:
        with TemporaryDirectory(prefix=".font-job-", dir=root) as directory:
            staging = Path(directory)
            result = repair_copy(source, staging / "font_embedded.pdf", selections, reference, **kwargs)
            result["job_id"] = job_id
            result["output_pdf"] = str(final / "font_embedded.pdf")
            result["report_dir"] = str(final)
            export_report(result, staging / "font-report.json")
            export_report({"repairs": result["matches"]}, staging / "font-report.csv")
            check_cancel(kwargs.get("is_cancelled"))
            if (
                file_hash(source) != result["input_sha256"]
                or file_hash(reference) != result["reference_sha256"]
            ):
                raise FontPreflightError("Source/reference changed before publication.")
            os.rename(staging, final)
        return result
    except Exception as exc:
        status = "CANCELLED" if isinstance(exc, PdfCancelled) else "FAILED_VALIDATION"
        # No text, font binaries, password or customer path in failure diagnostics.
        report = {
            "schema_version": 1,
            "job_id": job_id,
            "status": status,
            "reason": str(exc)
            if isinstance(exc, FontPreflightError)
            else "Backend operation could not be verified; no PDF published.",
            "output_pdf": "",
        }
        try:
            failure = root / ("font-" + job_id + "-failed.json")
            export_report(report, failure)
            exc.report_dir = str(root)
        except OSError:
            pass
        raise


def repair_batch(jobs, output_dir, *, progress=None, is_cancelled=None):
    """Explicit approved configuration per file; never borrow another file's xrefs."""
    from core.pdf_operations.analysis import PdfCancelled

    if not 1 <= len(jobs) <= 10000:
        raise FontPreflightError("Choose 1–10,000 approved jobs.")
    results = []
    for index, job in enumerate(jobs, 1):
        check_cancel(is_cancelled)
        try:
            result = repair_job(
                job["source"],
                output_dir,
                job.get("selections", {}),
                job.get("reference", ""),
                authorized_reference=job.get("authorized_reference") is True,
                policy=job.get("policy", "print"),
                is_cancelled=is_cancelled,
            )
        except PdfCancelled:
            raise
        except Exception:
            result = {
                "schema_version": 1,
                "status": "FAILED",
                "reason": "File blocked or failed validation; original retained.",
            }
            from composition.production.model import new_job_id

            export_report(result, Path(output_dir) / ("blocked-" + new_job_id() + ".json"))
        results.append({"file_index": index, **result})
        if progress:
            progress(index, len(jobs), f"Checked approved job {index}/{len(jobs)}")
    return {
        "schema_version": 1,
        "status": "VALIDATED" if all(r["status"] == "VALIDATED" for r in results) else "NEEDS_REVIEW",
        "files": results,
    }
