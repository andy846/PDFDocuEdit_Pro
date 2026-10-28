"""Selected-page extraction using the shared Workflow region semantics.

This internal job database is evidence for export, never production approval.
PDFs and SQLite connections are opened by their consuming worker only.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import fitz

from core.cancellation import TaskCancelled
from core.io_atomic import atomic_output
from workflow.extraction import ExtractionSpec, extract_page


def check_cancel(cancelled):
    if cancelled and cancelled():
        raise TaskCancelled()


def digest_file(path, cancelled=None):
    digest = hashlib.sha256()
    with Path(path).expanduser().open("rb") as stream:
        while chunk := stream.read(1024*1024):
            check_cancel(cancelled)
            digest.update(chunk)
    check_cancel(cancelled)
    return digest.hexdigest()


def signature(spec, pages):
    spec.validate()
    if not pages or any(type(p) is not int or p < 0 for p in pages) or sorted(set(pages)) != pages:
        raise ValueError("Select distinct pages in source order.")
    if any(r.scope != "all" for r in spec.regions):
        raise ValueError("Quick extraction regions apply to every selected page.")
    return hashlib.sha256(json.dumps([spec.to_dict(), pages], sort_keys=True).encode()).hexdigest()


def protect_target(target, paths):
    target = Path(target).expanduser().resolve()
    for source in paths:
        source = Path(source).expanduser().resolve()
        if target == source or (target.exists() and source.exists() and target.samefile(source)):
            raise ValueError("Output must not overwrite the source PDF or job database.")


@dataclass(frozen=True)
class QuickResult:
    database: str
    pages: int
    issues: int
    signature: str


def scan(source, spec, pages, target, *, protected=(), progress=None, is_cancelled=None):
    source, target = Path(source).expanduser(), Path(target).expanduser()
    pages = list(pages)
    identity = signature(spec, pages)
    protect_target(target, [source, *protected])
    digest = digest_file(source, is_cancelled)
    issues = 0
    with atomic_output(Path(target)) as temporary:
        with closing(sqlite3.connect(temporary)) as db, fitz.open(source) as pdf:
            if pdf.needs_pass or not pdf.page_count or pages[-1] >= pdf.page_count:
                raise ValueError("Select valid pages from an unlocked, nonempty PDF.")
            db.executescript("""
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE pages (ordinal INTEGER PRIMARY KEY, page INTEGER UNIQUE, issues TEXT);
                CREATE TABLE cells (page INTEGER, field TEXT, raw TEXT, value TEXT, issue TEXT,
                    PRIMARY KEY(page, field));
            """)
            for ordinal, index in enumerate(pages):
                check_cancel(is_cancelled)
                page = pdf[index]
                page_issues = []
                has_text = None
                for region in spec.regions:
                    check_cancel(is_cancelled)
                    raw, value, issue = extract_page(page, region)
                    if issue.startswith("Page size"):
                        issue = "Geometry Mismatch: " + issue
                    elif not raw.strip():
                        if has_text is None:
                            has_text = bool(page.get_text().strip())
                        if not has_text:
                            issue = "No extractable text layer on this page"
                    if issue:
                        issues += 1
                        page_issues.append(region.name + ": " + issue)
                    db.execute("INSERT INTO cells VALUES (?,?,?,?,?)", (index+1, region.name, raw, value, issue))
                db.execute("INSERT INTO pages VALUES (?,?,?)", (ordinal, index+1, "\n".join(page_issues)))
                if ordinal % 100 == 0:
                    db.commit()
                if progress and (ordinal % 25 == 0 or ordinal+1 == len(pages)):
                    progress(ordinal+1, len(pages), f"Extracting source page {index+1:,}")
            metadata = {"schema": 1, "accepted": False, "sha256": digest,
                        "source": str(Path(source).resolve()), "signature": identity,
                        "spec": spec.to_dict(), "pages": pages, "issues": issues,
                        "protected": [str(Path(p).expanduser().resolve()) for p in protected]}
            db.executemany("INSERT INTO meta VALUES (?,?)", [(k, json.dumps(v)) for k, v in metadata.items()])
            db.commit()
        if digest_file(source, is_cancelled) != digest:
            raise ValueError("Source changed during extraction; scan again.")
        check_cancel(is_cancelled)
    return QuickResult(str(target), len(pages), issues, identity)


class QuickStore:
    """Bounded queries; callers never load the entire job into Qt widgets."""
    def __init__(self, path):
        self.db = sqlite3.connect(Path(path).expanduser().resolve().as_uri() + "?mode=ro", uri=True)
        self.db.row_factory = sqlite3.Row

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    def metadata(self):
        return {r["key"]: json.loads(r["value"]) for r in self.db.execute("SELECT * FROM meta")}

    def details(self, page):
        return [dict(r) for r in self.db.execute("SELECT * FROM cells WHERE page=? ORDER BY rowid", (page,))]

    def rows(self, offset=0, limit=100):
        result = []
        for row in self.db.execute("SELECT * FROM pages ORDER BY ordinal LIMIT ? OFFSET ?",
                                   (max(1, min(int(limit), 100)), max(0, int(offset)))):
            result.append({"page": row["page"], "issues": row["issues"],
                           "status": "Issues" if row["issues"] else "Extracted",
                           "values": {c["field"]: c["value"] for c in self.details(row["page"])}})
        return result


def _csv_text(value):
    return "'" + value if value.lstrip(" \t\r\n\ufeff").startswith(("=", "+", "-", "@")) else value


def _xlsx_check(value):
    if len(value) > 32767 or len(value.encode("utf-16-le"))//2 > 32767 or any(
        not (ord(c) in (9, 10, 13) or 0x20 <= ord(c) <= 0xD7FF
             or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF) for c in value
    ):
        raise ValueError("XLSX cannot represent a value losslessly. Export CSV or TXT instead.")


def export(database, source, spec, pages, target, *, overwrite=False, progress=None,
           is_cancelled=None, on_committed=None):
    """Publish one artifact atomically; a late cancel cannot retract its receipt."""
    source, target = Path(source).expanduser(), Path(target).expanduser()
    identity = signature(spec, list(pages))
    with QuickStore(database) as store:
        meta = store.metadata()
        protect_target(target, [source, database, meta["source"], *meta["protected"]])
        if identity != meta["signature"] or digest_file(source, is_cancelled) != meta["sha256"]:
            raise ValueError("Extraction results are stale or the source changed; extract again.")
        suffix = Path(target).suffix.lower()
        if suffix not in (".xlsx", ".csv", ".txt"):
            raise ValueError("Choose XLSX, CSV or TXT output.")
        fields = [r.name for r in spec.regions]
        count = len(meta["pages"])
        if suffix == ".xlsx":
            if count+1 > 1048576 or count*len(fields)+1 > 1048576:
                raise ValueError("XLSX row limit exceeded; export CSV or TXT instead.")
            for row in store.db.execute("SELECT raw,value,issue FROM cells"):
                check_cancel(is_cancelled)
                for value in row:
                    _xlsx_check(value)
        with atomic_output(Path(target), overwrite=overwrite) as temporary:
            if suffix == ".xlsx":
                _write_xlsx(store, temporary, fields, count, progress, is_cancelled)
            else:
                with temporary.open("w", encoding="utf-8-sig" if suffix == ".csv" else "utf-8", newline="") as stream:
                    writer = csv.writer(stream, delimiter="," if suffix == ".csv" else "\t")
                    writer.writerow(["Source Page", "Row Status", "Row Issues", *fields,
                                     *[prefix+f for f in fields for prefix in ("Raw: ", "Status: ", "Issue: ")]])
                    for ordinal, row in enumerate(store.db.execute("SELECT * FROM pages ORDER BY ordinal")):
                        check_cancel(is_cancelled)
                        cells = store.details(row["page"])
                        values = [str(row["page"]), "Issues" if row["issues"] else "Extracted", row["issues"],
                                  *[c["value"] for c in cells],
                                  *[v for c in cells for v in (c["raw"], "Issue" if c["issue"] else "Extracted", c["issue"])]]
                        writer.writerow([_csv_text(v) for v in values] if suffix == ".csv" else values)
                        if progress and ordinal % 100 == 0:
                            progress(ordinal+1, count, "Writing extraction report")
            # Check source again before the commit, never after it.
            if digest_file(source, is_cancelled) != meta["sha256"]:
                raise ValueError("Source changed during export; extract again.")
            check_cancel(is_cancelled)
    if on_committed:
        on_committed(str(target))
    return str(target)


def _write_xlsx(store, target, fields, count, progress, cancelled):
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell

    book = Workbook(write_only=True)
    data, details, issues = [book.create_sheet(n) for n in ("Data", "Details", "Issues")]

    def append(sheet, values):
        cells = []
        for value in values:
            _xlsx_check(str(value))
            cell = WriteOnlyCell(sheet, value=str(value))
            cell.data_type = "s"
            cell.number_format = "@"
            cells.append(cell)
        sheet.append(cells)

    append(data, ["Source Page", "Row Status", "Row Issues", *fields])
    append(details, ["Source Page", "Field", "Raw", "Clean", "Status", "Issue"])
    append(issues, ["Source Page", "Field", "Issue"])
    # Provenance is metadata, not an additional success/approval claim.
    meta = store.metadata()
    data.sheet_properties.pageSetUpPr.fitToPage = True
    book.properties.description = "Snapshot SHA256: " + meta["sha256"] + "; extraction only; no production authorization"
    try:
        for ordinal, row in enumerate(store.db.execute("SELECT * FROM pages ORDER BY ordinal")):
            check_cancel(cancelled)
            cells = store.details(row["page"])
            append(data, [row["page"], "Issues" if row["issues"] else "Extracted", row["issues"], *[c["value"] for c in cells]])
            for cell in cells:
                append(details, [row["page"], cell["field"], cell["raw"], cell["value"],
                                 "Issue" if cell["issue"] else "Extracted", cell["issue"]])
                if cell["issue"]:
                    append(issues, [row["page"], cell["field"], cell["issue"]])
            if progress and ordinal % 100 == 0:
                progress(ordinal+1, count, "Writing extraction workbook")
        check_cancel(cancelled)
        book.save(target)
    finally:
        # Close write-only generators and remove their temporary worksheet files
        # also when cancellation occurs before Workbook.save().
        for sheet in book.worksheets:
            if not sheet.closed:
                sheet.close()
            if sheet._writer and Path(sheet._writer.out).exists():
                sheet._writer.cleanup()
        book.close()


def workflow_spec(source, spec, pages):
    """Existing nodes express selected-page provenance; no accepted state crosses."""
    from workflow.model import WorkflowNode, WorkflowSpec

    signature(spec, list(pages))
    result = WorkflowSpec.default().upgraded(6)
    result.name = "Extracted PDF regions"
    input_node, extraction = result.node("input"), result.node("extract")
    input_node.params = {"paths": [str(source)]}
    extraction.params = spec.to_dict()
    merge = WorkflowNode("merge", params={"pages": {str(source): ",".join(str(p+1) for p in pages)}})
    result.nodes.insert(1, merge)
    result.edges.remove([input_node.id, extraction.id])
    result.edges.extend([[input_node.id, merge.id], [merge.id, extraction.id]])
    for index, node in enumerate(result.nodes):
        node.x, node.y = (index % 3)*215, (index//3)*150
    result.validate()
    return result


def dispatch(request, *, progress=None, is_cancelled=None):
    operation = request["operation"]
    if operation == "rows":
        with QuickStore(request["database"]) as store:
            rows = store.rows(request.get("offset", 0))
            return {"rows": rows, "fields": [r["name"] for r in store.metadata()["spec"]["regions"]]}
    if operation == "preview":
        from workflow.worker import dispatch as workflow_dispatch
        return workflow_dispatch(request, progress, is_cancelled or (lambda: False))
    spec = ExtractionSpec.from_dict(request["extraction"])
    if operation == "scan":
        from dataclasses import asdict
        return asdict(scan(request["source"], spec, request["pages"], request["target"],
                           protected=request.get("protected", ()), progress=progress, is_cancelled=is_cancelled))
    if operation == "export":
        path = export(request["database"], request["source"], spec, request["pages"], request["target"],
                      overwrite=request.get("overwrite", False), progress=progress, is_cancelled=is_cancelled)
        return {"committed": path}
    if operation == "handoff":
        protect_target(request["target"], [request["source"], *request.get("protected", ())])
        before = digest_file(request["source"], is_cancelled)
        with atomic_output(Path(request["target"]), overwrite=False) as temporary:
            with Path(request["source"]).open("rb") as incoming, temporary.open("wb") as outgoing:
                while chunk := incoming.read(1024*1024):
                    check_cancel(is_cancelled)
                    outgoing.write(chunk)
            if digest_file(temporary, is_cancelled) != before or digest_file(request["source"], is_cancelled) != before:
                raise ValueError("Source changed during Workflow handoff.")
        return {"spec": workflow_spec(request["target"], spec, request["pages"]).to_dict()}
    raise ValueError("Unknown Quick Extraction operation.")
