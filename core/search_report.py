"""Standalone, streaming Deep Search exports."""

from __future__ import annotations

import csv
import html
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core.search_results_store import SearchResultsStore


@dataclass(frozen=True, slots=True)
class ReportMeta:
    query: str
    folder: str
    searched_at: str
    elapsed_seconds: float
    processed_files: int
    total_files: int
    include_subfolders: bool
    search_barcodes: bool
    completed: bool
    scope: str


def _safe_csv(value: object) -> str:
    text = str(value)
    # These values can originate from a PDF or file name. Keep CSV safe to open
    # in spreadsheet applications without executing a formula.
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _mark(value: str, keyword: str) -> str:
    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    result: list[str] = []
    previous = 0
    for match in pattern.finditer(value):
        result.append(html.escape(value[previous:match.start()]))
        result.append("<mark>" + html.escape(match.group()) + "</mark>")
        previous = match.end()
    result.append(html.escape(value[previous:]))
    return "".join(result)


def export_html(store: SearchResultsStore, target: str | Path, meta: ReportMeta,
                paths: tuple[str, ...] | None = None, keyword: str = "",
                source: str = "") -> Path:
    destination = Path(target)
    hits, files, pages = store.counts(paths, keyword, source)
    issues = store.issues()
    with destination.open("w", encoding="utf-8") as output:
        output.write("""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PDF Deep Search Report</title><style>
:root{font-family:system-ui,Segoe UI,sans-serif;color:#172437;background:#f3f6fa}
*{box-sizing:border-box}body{margin:0}.wrap{max-width:1100px;margin:auto;padding:34px 24px 72px}
header{background:#162b49;color:#fff;padding:34px;border-radius:14px}h1{margin:0 0 8px;font-size:2rem}
header p{margin:0;color:#d6e2f2}.badge{display:inline-block;padding:5px 11px;border-radius:20px;
background:#dbeafe;color:#174079;font-size:.85rem;font-weight:600}.warning{background:#fff0d6;color:#754a00}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:20px 0}.stat,.panel,.file{
background:white;border:1px solid #dce4ed;border-radius:11px;padding:20px}.stat strong{display:block;font-size:1.55rem}
.stat span,.muted{color:#596a7c}.panel{margin-bottom:20px}.meta{display:grid;grid-template-columns:150px 1fr;
gap:8px;overflow-wrap:anywhere}.meta dt{font-weight:700}.meta dd{margin:0}.file{margin:16px 0;break-inside:avoid-page}
.file h3{margin:0 0 5px}.path{font-size:.85rem;color:#596a7c;overflow-wrap:anywhere}
.hit{border-top:1px solid #e7edf3;padding:12px 0}.hit-head{font-size:.86rem;font-weight:700;color:#284f7b}
.context{margin:6px 0 0;white-space:pre-wrap;overflow-wrap:anywhere}mark{background:#ffe08a;border-radius:2px}
.issue{border-top:1px solid #e7edf3;padding:10px 0;overflow-wrap:anywhere}
@media(max-width:650px){.stats{grid-template-columns:repeat(2,1fr)}.meta{grid-template-columns:1fr;gap:2px}}
@media print{:root{background:white}.wrap{padding:0}header{background:white;color:#172437;border-bottom:2px solid #172437;
border-radius:0;padding:0 0 15px}header p{color:#596a7c}.panel,.file,.stat{box-shadow:none}a{color:inherit}}
</style></head><body><main class="wrap"><header><h1>PDF Deep Search Report</h1>
<p>Search results and source context</p></header>""")
        state = "Complete" if meta.completed else "Incomplete · search cancelled"
        output.write(f"<p><span class='badge{' warning' if not meta.completed else ''}'>"
                     f"{state}</span> <span class='badge'>{html.escape(meta.scope)}</span></p>")
        output.write("<section class='stats'>")
        for label, number in (("Occurrences", hits), ("Matching files", files),
                              ("Matching pages", pages), ("File errors", len(issues))):
            output.write(f"<div class='stat'><strong>{number:,}</strong><span>{label}</span></div>")
        output.write("</section><section class='panel'><h2>Search details</h2><dl class='meta'>")
        details = (("Keywords", meta.query), ("Folder", meta.folder),
                   ("Searched at", meta.searched_at),
                   ("Duration", f"{meta.elapsed_seconds:.2f} seconds"),
                   ("Files scanned", f"{meta.processed_files} of {meta.total_files}"),
                   ("Subfolders", "Included" if meta.include_subfolders else "Excluded"),
                   ("Barcodes", "Included" if meta.search_barcodes else "Excluded"))
        for label, value in details:
            output.write(f"<dt>{label}</dt><dd>{html.escape(value)}</dd>")
        output.write("</dl></section><section><h2>Matches</h2>")
        if hits == 0:
            output.write("<p>No matches in this export scope.</p>")
        previous_path = None
        for hit in store.iter_hits(paths, keyword, source):
            if hit.path != previous_path:
                if previous_path is not None:
                    output.write("</article>")
                output.write(f"<article class='file'><h3>{html.escape(hit.filename)}</h3>"
                             f"<div class='path'>{html.escape(hit.path)}</div>")
                previous_path = hit.path
            output.write(f"<div class='hit'><div class='hit-head'>Page {hit.page} · "
                         f"{html.escape(hit.keyword)} · {html.escape(hit.source.title())}</div>"
                         f"<p class='context'>{_mark(hit.context, hit.keyword)}</p></div>")
        if previous_path is not None:
            output.write("</article>")
        output.write("</section><section class='panel'><h2>Files that could not be searched</h2>")
        if issues:
            for issue in issues:
                output.write(f"<div class='issue'><b>{html.escape(issue.filename)}</b> · "
                             f"{html.escape(issue.message)}<div class='path'>"
                             f"{html.escape(issue.path)}</div></div>")
        else:
            output.write("<p>None.</p>")
        output.write("</section><p class='muted'>Pages without extractable text require OCR "
                     "before text searching.</p></main></body></html>")
    return destination


def export_csv(store: SearchResultsStore, target: str | Path, meta: ReportMeta,
               paths: tuple[str, ...] | None = None, keyword: str = "",
               source: str = "") -> Path:
    destination = Path(target)
    with destination.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.writer(output)
        writer.writerow(["Record type", "File name", "Path", "Page", "Keyword",
                         "Source", "Context", "Error", "Search status", "Export scope"])
        status = "complete" if meta.completed else "incomplete"
        for hit in store.iter_hits(paths, keyword, source):
            writer.writerow(["match", _safe_csv(hit.filename), _safe_csv(hit.path),
                             hit.page, _safe_csv(hit.keyword), hit.source,
                             _safe_csv(hit.context), "", status, meta.scope])
        for issue in store.issues():
            writer.writerow(["error", _safe_csv(issue.filename), _safe_csv(issue.path),
                             "", "", "", "", _safe_csv(issue.message), status, meta.scope])
    return destination


def export_text(store: SearchResultsStore, target: str | Path, meta: ReportMeta,
                paths: tuple[str, ...] | None = None, keyword: str = "",
                source: str = "") -> Path:
    destination = Path(target)
    hits, files, pages = store.counts(paths, keyword, source)
    with destination.open("w", encoding="utf-8") as output:
        output.write(f"PDF Deep Search Report\nStatus: {'Complete' if meta.completed else 'Incomplete'}\n"
                     f"Scope: {meta.scope}\nKeywords: {meta.query}\nFolder: {meta.folder}\n"
                     f"Searched at: {meta.searched_at}\nFiles scanned: "
                     f"{meta.processed_files}/{meta.total_files}\n"
                     f"Occurrences: {hits}; matching files: {files}; matching pages: {pages}\n\n")
        for hit in store.iter_hits(paths, keyword, source):
            output.write(f"{hit.filename} | Page {hit.page} | {hit.keyword} | {hit.source}\n"
                         f"{hit.path}\n{hit.context}\n\n")
        issues = store.issues()
        if issues:
            output.write("Files that could not be searched:\n")
            for issue in issues:
                output.write(f"{issue.path}: {issue.message}\n")
    return destination


def export_report(database_path: str | Path, target: str | Path, format_name: str,
                  meta: ReportMeta, paths: tuple[str, ...] | None = None,
                  keyword: str = "", source: str = "") -> Path:
    """Export from a read-only connection in a worker thread."""
    reader = SearchResultsStore.open_reader(database_path)
    destination = Path(target)
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.stem}-", suffix=destination.suffix, dir=destination.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        exporters = {".html": export_html, ".csv": export_csv, ".txt": export_text}
        exporters[format_name](reader, temporary, meta, paths, keyword, source)
        os.replace(temporary, destination)
        return destination
    finally:
        reader.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)
