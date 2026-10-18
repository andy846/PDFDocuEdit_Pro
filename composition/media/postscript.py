"""Stream declarative sheet selection into Ghostscript DSC output; no Qt widgets."""
from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path
from time import monotonic

import fitz

from composition.production.generator import check_cancel
from composition.template.model import CompositionError
from composition.template.serializer import file_hash

from .model import MediaSpec, PrinterProfile, validate_stock_mapping


def ghostscript_executable():
    from core.capabilities import _postscript_capability

    capability = _postscript_capability()
    if not capability.available:
        raise CompositionError("PostScript output requires Ghostscript. " + capability.guidance)
    return capability.path


def validate_output_backend(media):
    """Check the selected production dependency without creating output files."""
    if media.get("enabled"):
        spec = MediaSpec.from_dict(media)
        if PrinterProfile.from_dict(spec.printer_profile).backend == "postscript":
            ghostscript_executable()


def _run(executable, arguments, directory, is_cancelled, *, progress=None, total=0,
         stage="PostScript processing", output_policy=None, monitored=None, monitored_kind="PS"):
    """Keep diagnostics on disk and report bounded page updates / live heartbeats."""
    log = Path(directory)/"ghostscript.log"
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    with log.open("w+b") as stream, log.open("rb") as reader:
        # -q suppresses Ghostscript's PDF page notifications. Keep them in the
        # file-backed log, never an undrained pipe or the worker event protocol.
        process = subprocess.Popen([str(executable), "-dSAFER", "-dBATCH", "-dNOPAUSE", *arguments],
                                   cwd=directory, stdout=stream, stderr=subprocess.STDOUT, **options)
        started = last_page_at = monotonic()
        last_report, reported_page, page = started-1, -1, 0
        buffer = b""

        def report(*, finished=False):
            nonlocal buffer, page, last_page_at, last_report, reported_page
            data = reader.read(65536)
            lines = (buffer + data).split(b"\n")
            buffer = lines.pop()[-4096:]
            now = monotonic()
            for line in lines:
                match = re.fullmatch(rb"Page (\d+)\s*", line)
                if match and page < int(match[1]) <= total:
                    page = int(match[1])
                    last_page_at = now
            if not progress or (page == reported_page and now-last_report < 1 and not finished):
                return
            elapsed = int(now-started)
            position = f"processing page {page:,} / {total:,}" if page else "waiting for page progress"
            activity = "process finished" if finished else "process running"
            quiet = int(now-last_page_at)
            notice = f" · no new page report for {quiet}s" if quiet >= 30 and not finished else ""
            progress(max(0, page-1), total if page else 0,
                     f"{stage} · {position} · stage elapsed {elapsed//60:02d}:{elapsed%60:02d} · {activity}{notice}")
            last_report, reported_page = now, page

        try:
            report()
            while True:
                check_cancel(is_cancelled)
                if output_policy is not None and monitored is not None and Path(monitored).exists():
                    output_policy.check_size(monitored, monitored_kind)
                try:
                    process.wait(timeout=.2)
                    break
                except subprocess.TimeoutExpired:
                    report()
            report(finished=True)
            if process.returncode:
                stream.seek(max(0, stream.seek(0, 2)-4000))
                detail = stream.read(4000).decode("utf-8", errors="replace")
                raise CompositionError(f"PostScript conversion / validation failed ({process.returncode}): {detail}")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def ps_string(value):
    """ASCII-only PS literal with UTF-8 bytes escaped; input cannot become code."""
    return "(" + "".join(chr(c) if 32 <= c <= 126 and c not in (40, 41, 92)
                          else f"\\{c:03o}" for c in value.encode("utf-8")) + ")"


def selection_request(profile, stock):
    validate_stock_mapping(profile, stock)
    mapping = profile.mappings[stock["id"]]
    request = {"PageSize": [round(stock["width_mm"]*72/25.4, 3), round(stock["height_mm"]*72/25.4, 3)]}
    if profile.selection_mode == "tray":
        request.update(MediaPosition=mapping["media_position"], MediaType=None, MediaColor=None, MediaWeight=None)
    else:
        request.update(MediaPosition=None, MediaType=mapping["media_type"],
                       MediaColor=mapping.get("media_color") or None,
                       MediaWeight=stock["weight_gsm"] if profile.emit_media_weight else None)
    return request


def request_code(request):
    def literal(value):
        if value is None:
            return "null"
        if type(value) is bool:
            return "true" if value else "false"
        if isinstance(value, list):
            return "[" + " ".join(literal(v) for v in value) + "]"
        if isinstance(value, str):
            return ps_string(value)
        return str(value)
    return ("<< " + " ".join(f"/{key} {literal(value)}" for key, value in request.items())
            + " >> setpagedevice\n").encode("ascii")


def program_dsc(source, target, rows, media, expected_pages, audit, *, is_cancelled=None, progress=None, output_policy=None):
    """Accept only converter-produced sequential DSC pages; keep reads bounded."""
    # The worker callback reads a cancellation file. Calling it for every
    # ASCII PS line turns a streaming copy into millions of filesystem stats.
    # Keep immediate boundary checks and poll at most once per 50 ms in data.
    check_cancel(is_cancelled)
    next_cancel_check = monotonic() + .05
    spec = MediaSpec.from_dict(media)
    profile = PrinterProfile.from_dict(spec.printer_profile)
    stocks = {s["id"]: s for s in spec.stocks}
    rows = iter(rows)
    page = 0
    pending = None
    setups = 0
    saw_prolog = False
    if progress:
        progress(0, expected_pages, "PostScript media · programming sheet selections")
    with Path(source).open("rb") as input_stream, Path(target).open("wb") as output, Path(audit).open("w", encoding="utf-8-sig", newline="") as audit_stream:
        writer = csv.writer(audit_stream)
        writer.writerow(["File page", "Stock", "Side", "Selection programmed", "Request JSON"])
        # ps2write emits ASCII-encoded streams. A capped readline bounds even a long data line.
        start_of_line = True
        while line := input_stream.readline(1024*1024):
            if (is_cancelled or output_policy is not None) and monotonic() >= next_cancel_check:
                check_cancel(is_cancelled)
                if output_policy is not None:
                    output.flush()
                    output_policy.check_size(Path(target),"PS")
                next_cancel_check = monotonic() + .05
            if start_of_line and line.startswith(b"%%LanguageLevel:"):
                line = b"%%LanguageLevel: 3\n"
            if start_of_line and line == b"/SetPageSize true def\n" and page == 0:
                # The application owns physical sheet dimensions, not OPDFRead defaults.
                line = b"/SetPageSize false def\n"
            if start_of_line and line.startswith(b"%%Page:"):
                check_cancel(is_cancelled)
                match = re.fullmatch(rb"%%Page: \S+ (\d+)\s*", line)
                if not match or int(match[1]) != page+1 or pending is not None:
                    raise CompositionError("PostScript DSC page order / setup mismatch.")
                page += 1
                pending = next(rows, None)
                if pending is None or pending[0] != page or pending[8] not in stocks:
                    raise CompositionError("PostScript / media page reconciliation failed.")
            output.write(line)
            if start_of_line and line.strip() == b"%%EndProlog":
                saw_prolog = True
            if start_of_line and line.strip() == b"%%BeginPageSetup":
                if not saw_prolog or pending is None:
                    raise CompositionError("PostScript page setup has no matching media page.")
                stock, side = pending[8], pending[7]
                if side not in ("Front", "Back") or (not spec.duplex and side != "Front"):
                    raise CompositionError("Invalid PostScript sheet side.")
                request = selection_request(profile, stocks[stock])
                programmed = side == "Front"
                if programmed:
                    if page == 1:
                        request.update(Duplex=spec.duplex, Tumble=profile.tumble if spec.duplex else False)
                    output.write(f"% PDFDocuEdit sheet selection: page {page}, Stock {stock}\n".encode("ascii"))
                    output.write(request_code(request))
                writer.writerow([page, stock, side, programmed, json.dumps(request if programmed else {}, ensure_ascii=False)])
                pending = None
                setups += 1
                if progress and (setups % 100 == 0 or setups == expected_pages):
                    progress(setups, expected_pages, "PostScript media · programming sheet selections")
            start_of_line = line.endswith(b"\n")
    check_cancel(is_cancelled)
    if page != expected_pages or setups != page or next(rows, None) is not None:
        raise CompositionError(f"PostScript reconciliation failed: {page} pages / {setups} setups; expected {expected_pages}.")


def _prepare_converter_input(source_path, target, *, is_cancelled=None, progress=None):
    """Deduplicate objects/streams losslessly in a private converter input only.

    PDF assembly can repeat identical forms and font resources between chunks.
    Sharing these resources avoids repeatedly processing them in ps2write.
    No image resampling, font replacement or rasterisation is requested.
    MuPDF's save is synchronous; cancellation is checked before and after it.
    """
    check_cancel(is_cancelled)
    if progress:
        progress(0, 0, "PostScript preparation · lossless resource deduplication")
    check_cancel(is_cancelled)
    with fitz.open(source_path) as source:
        source.save(target, garbage=4, deflate=True)
        check_cancel(is_cancelled)
        with fitz.open(target) as prepared:
            if prepared.page_count != source.page_count:
                raise CompositionError("PostScript preparation changed the output page count.")
            for original, page in zip(source, prepared, strict=True):
                check_cancel(is_cancelled)
                if (original.mediabox, original.cropbox, original.rotation) != (
                        page.mediabox, page.cropbox, page.rotation):
                    raise CompositionError("PostScript preparation changed an output page geometry.")
    check_cancel(is_cancelled)


def export_postscript(directory, media, pdf_name, *, is_cancelled=None, progress=None, output_policy=None):
    """Called within a job's unpublished staging directory, including split packages."""
    spec = MediaSpec.from_dict(media)
    profile = PrinterProfile.from_dict(spec.printer_profile)
    if not spec.enabled or profile.backend != "postscript":
        return {}
    executable = ghostscript_executable()
    directory = Path(directory)
    if Path(pdf_name).name != pdf_name or not pdf_name.lower().endswith(".pdf"):
        raise CompositionError("PostScript export requires a package PDF filename.")
    pdf = directory/pdf_name
    target = pdf.with_suffix(".ps")
    if target.exists():
        raise CompositionError("PostScript output already exists.")
    with fitz.open(pdf) as source:
        count = source.page_count
    if progress:
        progress(0, 0, "PostScript conversion · starting converter")
    with tempfile.TemporaryDirectory(prefix=".postscript-", dir=directory) as temporary:
        folder = Path(temporary)
        raw, candidate, checked = folder/"converted.ps", folder/"production.ps", folder/"checked.pdf"
        audit = folder/"postscript-pages.csv"
        converter_input = folder/"converter-input.pdf"
        preparation_started = monotonic()
        _prepare_converter_input(pdf, converter_input, is_cancelled=is_cancelled, progress=progress)
        preparation_seconds = monotonic()-preparation_started
        conversion_started = monotonic()
        _run(executable, ["-sDEVICE=ps2write", "-dProduceDSC=true", f"-r{profile.resolution_dpi}",
                          "-dAutoRotatePages=/None", "-dEmbedAllFonts=true", "-dSubsetFonts=true",
                          f"-sOutputFile={raw.name}", "-f", str(converter_input.resolve())], folder, is_cancelled,
             progress=progress, total=count, stage="PostScript conversion", output_policy=output_policy, monitored=raw)
        conversion_seconds = monotonic()-conversion_started
        with closing(sqlite3.connect(directory/"media-plan.sqlite")) as db:
            rows = db.execute("SELECT * FROM pages ORDER BY file_page")
            program_dsc(raw, candidate, rows, media, count, audit, is_cancelled=is_cancelled, progress=progress, output_policy=output_policy)
        if output_policy is not None:
            output_policy.check_size(candidate,"PS")
        if progress:
            progress(0, 0, "PostScript validation · interpreting generated PostScript")
        validation_started = monotonic()
        from composition.production.output_policy import OutputPolicy
        validation_policy=OutputPolicy.from_dict() if output_policy is not None else None
        _run(executable, ["-sDEVICE=pdfwrite", "-dAutoRotatePages=/None", f"-r{profile.resolution_dpi}",
                          f"-sOutputFile={checked.name}", "-f", candidate.name], folder, is_cancelled,
             progress=progress, total=count, stage="PostScript validation", output_policy=validation_policy, monitored=checked, monitored_kind="PDF")
        with fitz.open(pdf) as source, fitz.open(checked) as verified:
            if verified.page_count != count:
                raise CompositionError("PostScript interpretation changed the output page count.")
            for index, (original, page) in enumerate(zip(source, verified, strict=True), 1):
                check_cancel(is_cancelled)
                if abs(original.rect.width-page.rect.width) > .5 or abs(original.rect.height-page.rect.height) > .5:
                    raise CompositionError("PostScript interpretation changed an output page size.")
                if progress and (index % 100 == 0 or index == count):
                    progress(index, count, "PostScript validation · checking page count and sizes")
        check_cancel(is_cancelled)
        summary = {"postscript": target.name, "postscript_pages": count, "postscript_sha256": file_hash(candidate),
                   "postscript_size": candidate.stat().st_size, "postscript_validation": "interpreted_page_count_and_size",
                   "selection_method": profile.selection_mode, "resolution_dpi": profile.resolution_dpi,
                   "device_validation": "pending",
                   "postscript_preparation_seconds": round(preparation_seconds, 3),
                   "postscript_input_bytes": pdf.stat().st_size,
                   "postscript_prepared_input_bytes": converter_input.stat().st_size,
                   "postscript_conversion_seconds": round(conversion_seconds, 3),
                   "postscript_validation_seconds": round(monotonic()-validation_started, 3)}
        from core.postscript_cache import capture_production_preview
        capture_production_preview(checked, summary["postscript_sha256"], executable, profile.resolution_dpi)
        candidate.rename(target)
        audit.rename(directory/"postscript-pages.csv")
        (directory/"postscript-report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        summary_file = directory/"media-summary.json"
        if summary_file.is_file():
            values = json.loads(summary_file.read_text(encoding="utf-8"))
            summary_file.write_text(json.dumps({**values, **summary}, indent=2), encoding="utf-8")
        return summary


def discard_postscript(directory, summary):
    """Late failure/cancellation retains diagnostics, never a print-ready PS."""
    directory = Path(directory)
    for path in directory.glob("*.ps"):
        path.unlink(missing_ok=True)
    (directory/"postscript-report.json").unlink(missing_ok=True)
    if "postscript" in summary:
        summary.update(postscript="", postscript_validation="not_published")
    summary_file = directory/"media-summary.json"
    if summary_file.is_file():
        values = json.loads(summary_file.read_text(encoding="utf-8"))
        if "postscript" in values:
            values.update(postscript="", postscript_validation="not_published")
            summary_file.write_text(json.dumps(values, indent=2), encoding="utf-8")


def export_paper_test(target, media, *, is_cancelled=None, progress=None):
    """A small operator proof using profile mappings, without any customer data."""
    import shutil

    from core.io_atomic import atomic_output

    from .ticket import export_rows

    spec = MediaSpec.from_dict(media)
    profile = PrinterProfile.from_dict(spec.printer_profile)
    if not spec.enabled or profile.backend != "postscript":
        raise CompositionError("Enable Media Assignment and choose PostScript for a paper-selection test.")
    target = Path(target).with_suffix(".ps")
    target.parent.mkdir(parents=True, exist_ok=True)
    requests = {}
    for stock in spec.stocks:
        request = validate_stock_mapping(profile, stock)
        if request in requests:
            raise CompositionError(f"Stocks {requests[request]} and {stock['id']} have identical paper-selection requests.")
        requests[request] = stock["id"]
    sides = 2 if spec.duplex else 1
    with tempfile.TemporaryDirectory(prefix=".paper-test-", dir=target.parent) as temporary:
        folder = Path(temporary)
        with fitz.open() as pdf:
            for stock in spec.stocks:
                for side in range(sides):
                    check_cancel(is_cancelled)
                    page = pdf.new_page(width=stock["width_mm"]*72/25.4, height=stock["height_mm"]*72/25.4)
                    label = f"PAPER SELECTION TEST\nStock: {stock['id']}\n{'BACK' if side else 'FRONT'}\nCheck the actual paper before production."
                    page.insert_text((20, 25), label, fontsize=10)
            pdf.save(folder/"paper-test.pdf")
        def rows():
            number = 0
            for record, stock in enumerate(spec.stocks, 1):
                for side in range(sides):
                    number += 1
                    yield [number, number, record, "", side+1, "SINGLE", 1,
                           "Back" if side else "Front", stock["id"], "Paper-selection test"]
        export_rows(folder, media, rows(), len(spec.stocks)*sides, "paper-test.pdf", is_cancelled=is_cancelled)
        summary = export_postscript(folder, media, "paper-test.pdf", is_cancelled=is_cancelled, progress=progress)
        check_cancel(is_cancelled)
        with atomic_output(target) as staged:
            shutil.copyfile(folder/"paper-test.ps", staged)
        return {"path": str(target), "pages": summary["postscript_pages"], "stocks": len(spec.stocks)}
