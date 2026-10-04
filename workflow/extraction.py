"""Visual, millimetre-based text extraction with disk-backed page evidence."""
from __future__ import annotations

import csv
import json
import math
import re
import sqlite3
from contextlib import closing, nullcontext
from dataclasses import asdict, dataclass, field
from pathlib import Path

import fitz

from composition.production.generator import check_cancel
from composition.template.model import MM_TO_PT, CompositionError
from composition.template.serializer import file_hash
from core.io_atomic import atomic_output


@dataclass
class Region:
    name: str = "Account_No"
    x_mm: float = 20
    y_mm: float = 20
    width_mm: float = 80
    height_mm: float = 10
    page_width_mm: float = 210
    page_height_mm: float = 297
    scope: str = "all"
    role: int = 1
    remove_label: str = ""
    trim: bool = True
    join_lines: bool = True
    required: bool = True
    format: str = "text"
    min_length: int = 0
    max_length: int = 1024
    envelope_value: str = "first"

    def validate(self):
        if not isinstance(self.name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", self.name):
            raise CompositionError("Field names need letters, digits or underscores; start with a letter/underscore.")
        for key in ("x_mm", "y_mm", "width_mm", "height_mm", "page_width_mm", "page_height_mm"):
            value = getattr(self, key)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise CompositionError("Region coordinates must be finite millimetres.")
        if (min(self.x_mm, self.y_mm) < 0 or min(self.width_mm, self.height_mm) <= 0
                or not 1 <= self.page_width_mm <= 2000 or not 1 <= self.page_height_mm <= 2000
                or self.x_mm + self.width_mm > self.page_width_mm + .05
                or self.y_mm + self.height_mm > self.page_height_mm + .05):
            raise CompositionError("Region extends beyond its reference page.")
        if self.scope not in ("all", "first", "role") or type(self.role) is not int or not 1 <= self.role <= 100:
            raise CompositionError("Choose all pages, first page or a positive page role.")
        if self.envelope_value not in ("first", "consistent") or self.format not in ("text", "digits", "decimal"):
            raise CompositionError("Unsupported extraction format or envelope policy.")
        if any(type(getattr(self, key)) is not bool for key in ("trim", "join_lines", "required")):
            raise CompositionError("Invalid region switches.")
        if (type(self.min_length) is not int or type(self.max_length) is not int
                or not 0 <= self.min_length <= self.max_length <= 100000
                or not isinstance(self.remove_label, str) or len(self.remove_label) > 1024):
            raise CompositionError("Invalid text label or length limits.")

    def clean(self, raw):
        value = raw
        if self.remove_label and value.lstrip().startswith(self.remove_label):
            value = value.lstrip()[len(self.remove_label):]
        if self.join_lines:
            value = " ".join(value.splitlines())
        return value.strip() if self.trim else value

    def problem(self, value):
        if self.required and not value.strip():
            return "Required field is empty"
        if not self.min_length <= len(value) <= self.max_length:
            return "Value does not match configured length"
        if value and self.format == "digits" and not re.fullmatch(r"[0-9]+", value):
            return "Expected ASCII digits (leading zeros are preserved)"
        if value and self.format == "decimal" and not re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", value):
            return "Expected a decimal value"
        return ""


@dataclass
class ExtractionSpec:
    regions: list[Region] = field(default_factory=list)
    version: int = 1

    def validate(self):
        if type(self.version) is not int or self.version != 1 or not 1 <= len(self.regions) <= 200:
            raise CompositionError("Configure between 1 and 200 named regions.")
        names = set()
        for region in self.regions:
            region.validate()
            if region.name in names:
                raise CompositionError("Duplicate region field: " + region.name)
            names.add(region.name)

    @classmethod
    def from_dict(cls, raw):
        try:
            result = cls(**{**raw, "regions": [Region(**item) for item in raw["regions"]]})
            result.validate()
            return result
        except (KeyError, TypeError) as exc:
            raise CompositionError("Invalid extraction configuration") from exc

    def to_dict(self):
        return asdict(self)


@dataclass
class ExtractionResult:
    database: str
    source_sha256: str
    pages: int
    fields: list[str]
    issues: int


def extract_page(page, region):
    """Coordinates are visible-page mm, transformed to unrotated PDF coordinates."""
    width, height = page.rect.width / MM_TO_PT, page.rect.height / MM_TO_PT
    if abs(width - region.page_width_mm) > .15 or abs(height - region.page_height_mm) > .15:
        return "", "", "Page size differs from the reference; configure a matching region"
    rect = fitz.Rect(region.x_mm, region.y_mm, region.x_mm + region.width_mm,
                     region.y_mm + region.height_mm) * MM_TO_PT
    raw = page.get_text("text", clip=rect * page.derotation_matrix, sort=True)
    value = region.clean(raw)
    return raw, value, region.problem(value)


def scan_pdf(source, spec, target, *, progress=None, is_cancelled=None):
    spec.validate()
    if Path(source).resolve()==Path(target).resolve():
        raise CompositionError("Extraction output must not overwrite its PDF source.")
    digest = file_hash(Path(source))
    with atomic_output(Path(target)) as temp:
        with closing(sqlite3.connect(temp)) as db, fitz.open(source) as pdf:
            if pdf.needs_pass or not pdf.page_count:
                raise CompositionError("Unlock a nonempty text-layer PDF before extraction.")
            db.executescript("""
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE cells (page INTEGER, field TEXT, raw TEXT, value TEXT, issue TEXT,
                    applicable INTEGER, PRIMARY KEY(page,field));
                CREATE TABLE edits (page INTEGER, field TEXT, old_value TEXT, new_value TEXT, reason TEXT);
                CREATE TABLE groups (envelope INTEGER PRIMARY KEY, start INTEGER, end INTEGER);
                CREATE TABLE envelope_cells (envelope INTEGER, field TEXT, value TEXT, issue TEXT, issue_page INTEGER,
                    PRIMARY KEY(envelope,field));
                CREATE TABLE group_edits (old_groups TEXT, new_groups TEXT, reason TEXT);
                CREATE TABLE provenance (page INTEGER PRIMARY KEY, source_file TEXT, source_page INTEGER);
            """)
            issues = 0
            for index in range(pdf.page_count):
                check_cancel(is_cancelled)
                page = pdf[index]
                has_text = None
                for region in spec.regions:
                    # First/role scopes are resolved after grouping, not guessed here.
                    raw, value, issue = extract_page(page, region)
                    if not raw.strip() and not issue.startswith("Page size"):
                        if has_text is None:
                            has_text = bool(page.get_text().strip())
                        if not has_text:
                            issue = "No extractable text layer on this page"
                    issues += bool(issue)
                    db.execute("INSERT INTO cells VALUES (?,?,?,?,?,1)", (index+1, region.name, raw, value, issue))
                if index % 100 == 0:
                    db.commit()
                if progress and (index % 25 == 0 or index+1 == pdf.page_count):
                    progress(index+1, pdf.page_count, f"Extracting page {index+1:,}/{pdf.page_count:,}")
            pages = pdf.page_count
            db.executemany("INSERT INTO provenance VALUES (?,?,?)",((n,str(source),n) for n in range(1,pages+1)))
            db.executemany("INSERT INTO meta VALUES (?,?)", [("sha256", digest), ("pages", str(pages)),
                         ("spec", json.dumps(spec.to_dict())), ("accepted", "false")])
            db.commit()
        check_cancel(is_cancelled)
        if file_hash(Path(source)) != digest:
            raise CompositionError("Source changed during extraction; scan again.")
    return ExtractionResult(str(target), digest, pages, [r.name for r in spec.regions], issues)


class ExtractionStore:
    """One connection per worker/caller. No global cross-thread PDF or database handles."""
    def __init__(self, path):
        self.path = str(path)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    def metadata(self):
        return {r["key"]: r["value"] for r in self.db.execute("SELECT * FROM meta")}

    def page(self, number):
        return [dict(r) for r in self.db.execute("SELECT * FROM cells WHERE page=? ORDER BY field", (number,))]

    def values(self, number):
        return {r["field"]: r["value"] for r in self.db.execute("SELECT field,value FROM cells WHERE page=?", (number,))}

    def issues(self):
        return self.db.execute("SELECT COUNT(*) FROM cells WHERE applicable=1 AND issue!=''").fetchone()[0] + self.db.execute(
            "SELECT COUNT(*) FROM envelope_cells WHERE issue!=''").fetchone()[0]

    def grouped(self, groups, spec, *, progress=None, is_cancelled=None, commit=True):
        spec.validate()
        pages = int(self.metadata()["pages"])
        cursor = 1
        for start, end in groups:
            if type(start) is not int or type(end) is not int or start != cursor or not start <= end <= pages:
                raise CompositionError("Groups must cover every source page once, in order.")
            cursor = end+1
        if not groups or cursor != pages+1:
            raise CompositionError("Groups do not cover the source PDF.")
        with self.db if commit else nullcontext():
            self.db.execute("DELETE FROM groups")
            self.db.execute("DELETE FROM envelope_cells")
            self.db.execute("UPDATE cells SET applicable=0")
            for ordinal, (start, end) in enumerate(groups, 1):
                check_cancel(is_cancelled)
                self.db.execute("INSERT INTO groups VALUES (?,?,?)", (ordinal, start, end))
                for region in spec.regions:
                    selected = list(range(start, end+1)) if region.scope == "all" else [start + (region.role-1 if region.scope == "role" else 0)]
                    selected = [n for n in selected if n <= end]
                    for number in selected:
                        self.db.execute("UPDATE cells SET applicable=1 WHERE page=? AND field=?", (number, region.name))
                    first = selected[0] if selected else None
                    value = self.values(first).get(region.name, "") if first else ""
                    issue = "Requested page role is absent" if not selected else region.problem(value)
                    issue_page=first or start
                    if region.envelope_value == "consistent":
                        for number in selected:
                            row = self.db.execute("SELECT value,issue FROM cells WHERE page=? AND field=?", (number,region.name)).fetchone()
                            if row["issue"] or row["value"] != value:
                                issue = f"Values missing or inconsistent within envelope (page {number})"
                                issue_page=number
                                break
                    self.db.execute("INSERT INTO envelope_cells VALUES (?,?,?,?,?)", (ordinal,region.name,value,issue,issue_page))
                if progress and ordinal % 100 == 0:
                    progress(ordinal,len(groups),"Building envelope data")
            self.db.execute("UPDATE meta SET value='false' WHERE key='accepted'")

    def correct(self, page, field_name, value, reason, *, commit=True):
        spec = ExtractionSpec.from_dict(json.loads(self.metadata()["spec"]))
        region = next((r for r in spec.regions if r.name == field_name), None)
        row = self.db.execute("SELECT value FROM cells WHERE page=? AND field=?", (page,field_name)).fetchone()
        if not region or not row or not isinstance(value,str) or not reason.strip() or len(reason)>1000:
            raise CompositionError("A correction needs a valid cell, value and reason.")
        with self.db if commit else nullcontext():
            self.db.execute("INSERT INTO edits VALUES (?,?,?,?,?)", (page,field_name,row[0],value,reason))
            self.db.execute("UPDATE cells SET value=?,issue=? WHERE page=? AND field=?", (value,region.problem(value),page,field_name))
            self.db.execute("UPDATE meta SET value='false' WHERE key='accepted'")

    def accept(self):
        groups=[list(row) for row in self.db.execute("SELECT start,end FROM groups ORDER BY envelope")]
        from composition.pdf_source.model import EnvelopeSettings
        from composition.pdf_source.planner import EnvelopePlan
        if not groups:
            raise CompositionError("Complete envelope grouping before accepting review.")
        EnvelopePlan(int(self.metadata()["pages"]),EnvelopeSettings(pages_per_envelope=1,groups=groups))
        if self.issues():
            raise CompositionError("Resolve extraction and envelope findings before accepting review.")
        with self.db:
            self.db.execute("UPDATE meta SET value='true' WHERE key='accepted'")

    def production_values(self, plan):
        values = {"Page_"+k:v for k,v in self.values(plan.source_page).items()} if plan.source_page else {
            "Page_"+r.name:"" for r in ExtractionSpec.from_dict(json.loads(self.metadata()["spec"])).regions}
        values.update({"Envelope_"+row["field"]:row["value"] for row in self.db.execute(
            "SELECT field,value FROM envelope_cells WHERE envelope=?", (plan.envelope,))})
        return values

    def export(self, target):
        target=Path(target)
        protected={Path(self.path).resolve(),*(Path(r[0]).resolve() for r in self.db.execute("SELECT DISTINCT source_file FROM provenance") if r[0])}
        if target.resolve() in protected:
            raise CompositionError("A CSV report must not overwrite an extraction database or source PDF.")
        with atomic_output(Path(target)) as temp, temp.open("w",encoding="utf-8-sig",newline="") as stream:
            writer=csv.writer(stream)
            writer.writerow(["Workflow source page","Envelope","Field","Raw text","Value","Issue","Applicable","Original source file","Original source page","Scope"])
            for row in self.db.execute("SELECT cells.*,groups.envelope,provenance.source_file,provenance.source_page FROM cells LEFT JOIN groups ON page BETWEEN start AND end LEFT JOIN provenance USING(page) ORDER BY page,field"):
                # Treat cells as spreadsheet text; prevent imported values executing formulas.
                vals=[row[k] for k in ("page","envelope","field","raw","value","issue","applicable","source_file","source_page")]
                vals.append("Page")
                writer.writerow(["'"+v if isinstance(v,str) and v.startswith(("=","+","-","@")) else v for v in vals])
            for row in self.db.execute("SELECT * FROM envelope_cells ORDER BY envelope,field"):
                original=self.db.execute("SELECT source_file,source_page FROM provenance WHERE page=?",(row["issue_page"],)).fetchone()
                vals=[row["issue_page"],row["envelope"],row["field"],"",row["value"],row["issue"],1,
                      original[0] if original else "",original[1] if original else "","Envelope"]
                writer.writerow(["'"+v if isinstance(v,str) and v.startswith(("=","+","-","@")) else v for v in vals])
