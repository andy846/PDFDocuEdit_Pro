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


def _run(executable, arguments, directory, is_cancelled):
    """File-backed diagnostics and cooperative subprocess cancellation."""
    log = Path(directory)/"ghostscript.log"
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    with log.open("w+b") as stream:
        process = subprocess.Popen([str(executable), "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", *arguments],
                                   cwd=directory, stdout=stream, stderr=subprocess.STDOUT, **options)
        try:
            while True:
                check_cancel(is_cancelled)
                try:
                    process.wait(timeout=.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
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


def program_dsc(source, target, rows, media, expected_pages, audit, *, is_cancelled=None):
    """Accept only converter-produced sequential DSC pages; keep reads bounded."""
    spec = MediaSpec.from_dict(media)
    profile = PrinterProfile.from_dict(spec.printer_profile)
    stocks = {s["id"]: s for s in spec.stocks}
    rows = iter(rows)
    page = 0
    pending = None
    setups = 0
    saw_prolog = False
    with Path(source).open("rb") as input_stream, Path(target).open("wb") as output, Path(audit).open("w", encoding="utf-8-sig", newline="") as audit_stream:
        writer = csv.writer(audit_stream)
        writer.writerow(["File page", "Stock", "Side", "Selection programmed", "Request JSON"])
        # ps2write emits ASCII-encoded streams. A capped readline bounds even a long data line.
        start_of_line = True
        while line := input_stream.readline(1024*1024):
            check_cancel(is_cancelled)
            if start_of_line and line.startswith(b"%%LanguageLevel:"):
                line = b"%%LanguageLevel: 3\n"
            if start_of_line and line == b"/SetPageSize true def\n" and page == 0:
                # The application owns physical sheet dimensions, not OPDFRead defaults.
                line = b"/SetPageSize false def\n"
            if start_of_line and line.startswith(b"%%Page:"):
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
            start_of_line = line.endswith(b"\n")
    if page != expected_pages or setups != page or next(rows, None) is not None:
        raise CompositionError(f"PostScript reconciliation failed: {page} pages / {setups} setups; expected {expected_pages}.")


def export_postscript(directory, media, pdf_name, *, is_cancelled=None, progress=None):
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
        progress(0, count, "Converting validated PDF to PostScript")
    with tempfile.TemporaryDirectory(prefix=".postscript-", dir=directory) as temporary:
        folder = Path(temporary)
        raw, candidate, checked = folder/"converted.ps", folder/"production.ps", folder/"checked.pdf"
        audit = folder/"postscript-pages.csv"
        _run(executable, ["-sDEVICE=ps2write", "-dProduceDSC=true", f"-r{profile.resolution_dpi}",
                          "-dAutoRotatePages=/None", "-dEmbedAllFonts=true", "-dSubsetFonts=true",
                          f"-sOutputFile={raw.name}", "-f", str(pdf.resolve())], folder, is_cancelled)
        with closing(sqlite3.connect(directory/"media-plan.sqlite")) as db:
            rows = db.execute("SELECT * FROM pages ORDER BY file_page")
            program_dsc(raw, candidate, rows, media, count, audit, is_cancelled=is_cancelled)
        if progress:
            progress(count, count, "Interpreting PostScript and checking output pages")
        _run(executable, ["-sDEVICE=pdfwrite", "-dAutoRotatePages=/None", f"-r{profile.resolution_dpi}",
                          f"-sOutputFile={checked.name}", "-f", candidate.name], folder, is_cancelled)
        with fitz.open(pdf) as source, fitz.open(checked) as verified:
            if verified.page_count != count:
                raise CompositionError("PostScript interpretation changed the output page count.")
            for original, page in zip(source, verified, strict=True):
                check_cancel(is_cancelled)
                if abs(original.rect.width-page.rect.width) > .5 or abs(original.rect.height-page.rect.height) > .5:
                    raise CompositionError("PostScript interpretation changed an output page size.")
        check_cancel(is_cancelled)
        summary = {"postscript": target.name, "postscript_pages": count, "postscript_sha256": file_hash(candidate),
                   "postscript_size": candidate.stat().st_size, "postscript_validation": "interpreted_page_count_and_size",
                   "selection_method": profile.selection_mode, "resolution_dpi": profile.resolution_dpi,
                   "device_validation": "pending"}
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
