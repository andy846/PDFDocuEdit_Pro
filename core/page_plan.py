"""Organizer selection, immutable page plans and shared PDF materialization."""

from __future__ import annotations

import math
import re
import tempfile
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path

import fitz

from core.diagnostics import log_failure

from .io_atomic import atomic_output
from .pdf_io import validate_pdf_file

POINTS_PER_MM = 72 / 25.4


@dataclass(frozen=True)
class PagePlanEntry:
    entry_id: str
    source_kind: str
    source_page: int
    source_path: str = ""
    final_rotation: int = 0
    password: str = ""
    page_size: tuple[float, float] | None = None
    crop_box: tuple[float, float, float, float] | None = None
    source_label: str = ""


def parse_page_selection(expression: str, page_count: int) -> list[int]:
    """Strict one-based selections in the current plan, returned zero-based."""
    if page_count < 0:
        raise ValueError("Invalid page count.")
    if not expression.strip():
        return []
    result = set()
    for raw in expression.split(","):
        part = " ".join(raw.casefold().split())
        if part in {"all", "odd", "even"}:
            result.update(range(0 if part != "even" else 1, page_count, 1 if part == "all" else 2))
            continue
        every = re.fullmatch(r"every (\d+)(?:st|nd|rd|th)? pages?", part)
        last = re.fullmatch(r"last (\d+) pages?", part)
        if every or last:
            amount = int((every or last).group(1))
            if amount < 1:
                raise ValueError("Page interval/count must be greater than zero.")
            result.update(range(amount - 1, page_count, amount) if every else range(max(0, page_count - amount), page_count))
            continue
        numbers = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", part)
        if not numbers:
            raise ValueError(f"Invalid page selection: {raw}")
        first, last_page = sorted((int(numbers[1]), int(numbers[2] or numbers[1])))
        if first < 1 or last_page > page_count:
            raise ValueError(f"Pages must be between 1 and {page_count}: {raw}")
        result.update(range(first - 1, last_page))
    return sorted(result)


def reverse_selected(entries: list[PagePlanEntry], positions: Iterable[int]) -> list[PagePlanEntry]:
    result = entries.copy()
    slots = sorted(set(positions))
    for index, entry in zip(slots, reversed([entries[i] for i in slots]), strict=True):
        result[index] = entry
    return result


def duplicate_entries(entries: Iterable[PagePlanEntry]) -> list[PagePlanEntry]:
    return [replace(entry, entry_id=uuid.uuid4().hex) for entry in entries]


def blank_entry(width: float, height: float) -> PagePlanEntry:
    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
        raise ValueError("Blank page dimensions must be positive finite values.")
    return PagePlanEntry(uuid.uuid4().hex, "blank", -1, page_size=(width, height))


def interleave_entries(a: list[PagePlanEntry], b: list[PagePlanEntry], *, b_first=False, reverse_b=False,
                       pad=False, size_of: Callable[[PagePlanEntry], tuple[float, float]] | None = None) -> list[PagePlanEntry]:
    if not a or not b:
        raise ValueError("Both interleave sources must contain pages.")
    b = list(reversed(b)) if reverse_b else b
    result = []
    for i in range(max(len(a), len(b))):
        left = a[i] if i < len(a) else None
        right = b[i] if i < len(b) else None
        if pad and (left is None or right is None):
            if size_of is None:
                raise ValueError("Padding requires a page-size provider.")
            blank = blank_entry(*size_of(left or right))
            left, right = (blank, right) if left is None else (left, blank)
        result.extend(entry for entry in ((right, left) if b_first else (left, right)) if entry is not None)
    return result


def apply_transform(page: fitz.Page, entry: PagePlanEntry) -> None:
    if entry.crop_box is not None and page.cropbox != fitz.Rect(entry.crop_box):
        page.set_cropbox(fitz.Rect(entry.crop_box))
    if page.rotation != entry.final_rotation % 360:
        page.set_rotation(entry.final_rotation % 360)


class PlanReader:
    """One thread owns the reader and its external documents for its lifetime."""

    def __init__(self, current: fitz.Document):
        self.current = current
        self.sources: dict[tuple[str, str], fitz.Document] = {}
        self._previews: dict[tuple[str, str], fitz.Document] = {}
        self._ocg_tags = {}
        self._copy_sources = {}

    def source(self, entry: PagePlanEntry) -> fitz.Document:
        if entry.source_kind == "current":
            return self.current
        if entry.source_kind != "external":
            raise ValueError(f"Unknown page source: {entry.source_kind}")
        key = (entry.source_path, entry.password)
        if key not in self.sources:
            source = fitz.open(entry.source_path)
            if source.needs_pass and not source.authenticate(entry.password):
                source.close()
                raise ValueError(f"Cannot unlock {entry.source_label or Path(entry.source_path).name}.")
            self.sources[key] = source
        return self.sources[key]

    def box(self, entry: PagePlanEntry) -> fitz.Rect:
        if entry.crop_box is not None:
            return fitz.Rect(entry.crop_box)
        if entry.source_kind == "blank":
            width, height = entry.page_size or (595, 842)
            return fitz.Rect(0, 0, width, height)
        return self.source(entry).load_page(entry.source_page).cropbox

    def size(self, entry: PagePlanEntry) -> tuple[float, float]:
        box = self.box(entry)
        return (box.height, box.width) if entry.final_rotation % 180 else (box.width, box.height)

    def append(self, output: fitz.Document, entry: PagePlanEntry) -> None:
        if entry.source_kind == "blank":
            width, height = entry.page_size or (595, 842)
            blank_entry(width, height)  # validate dimensions
            output.new_page(width=width, height=height)
        else:
            source = self.source(entry)
            if not 0 <= entry.source_page < source.page_count:
                raise ValueError("Page plan references an invalid source page.")
            if source.get_ocgs():
                identity = id(source)
                if identity not in self._copy_sources:
                    self._copy_sources[identity] = fitz.open(
                        stream=source.tobytes(garbage=0, deflate=False, clean=False, no_new_id=True), filetype="pdf")
                source = self._copy_sources[identity]
            tags = self._tag_optional_content(source)
            previous_xref = output.xref_length()
            output.insert_pdf(source, from_page=entry.source_page, to_page=entry.source_page)
            self._register_optional_content(output, previous_xref, tags)
        apply_transform(output[-1], entry)

    def _tag_optional_content(self, source):
        # insert_pdf copies OCG objects but not the source catalogue's display
        # configuration. Tag this private reader document to identify grafted
        # groups unambiguously, including groups with identical names.
        identity = id(source)
        if identity not in self._ocg_tags:
            tags = {}
            for xref, info in source.get_ocgs().items():
                tag = uuid.uuid4().hex
                source.xref_set_key(xref, "OrganizerOCG", f"({tag})")
                tags[tag] = bool(info["on"])
            self._ocg_tags[identity] = tags
        return self._ocg_tags[identity]

    @staticmethod
    def _register_optional_content(output, first_xref, tags):
        if not tags:
            return
        copied = {}
        for xref in range(first_xref, output.xref_length()):
            kind, tag = output.xref_get_key(xref, "OrganizerOCG")
            if kind == "string" and tag in tags:
                copied[xref] = tags[tag]
                # MuPDF compares resolved group dictionaries when selecting
                # their states. Keep each copied instance distinct even when
                # names and all standard keys are identical.
                output.xref_set_key(xref, "OrganizerOCG", f"({uuid.uuid4().hex})")
        if not copied:
            return
        catalog = output.pdf_catalog()
        if output.xref_get_key(catalog, "OCProperties")[0] == "null":
            output.xref_set_key(catalog, "OCProperties", "<</OCGs [] /D <</BaseState /ON /ON [] /OFF []>>>>")
        groups = output.xref_get_key(catalog, "OCProperties/OCGs")[1]
        references = list(dict.fromkeys(
            [int(value) for value in re.findall(r"(\d+)\s+\d+\s+R", groups)] + list(copied)
        ))
        output.xref_set_key(catalog, "OCProperties/OCGs", "[" + " ".join(f"{xref} 0 R" for xref in references) + "]")
        for key, state in (("ON", True), ("OFF", False)):
            old = output.xref_get_key(catalog, f"OCProperties/D/{key}")[1]
            values = [int(value) for value in re.findall(r"(\d+)\s+\d+\s+R", old)]
            values.extend(xref for xref, visible in copied.items() if visible == state)
            output.xref_set_key(catalog, f"OCProperties/D/{key}", "[" + " ".join(f"{xref} 0 R" for xref in dict.fromkeys(values)) + "]")
        # Re-read the modified catalogue so the current render context picks up
        # the added default states as well as the saved document.
        pdf = fitz.mupdf.pdf_document_from_fz_document(output.this)
        fitz.mupdf.ll_pdf_drop_ocg(pdf.m_internal)
        # MuPDF drop frees the descriptor but does not clear this pointer.
        # Clear it before read/close to prevent use-after-free/double-free.
        pdf.m_internal.ocg = None
        fitz.mupdf.ll_pdf_read_ocg(pdf.m_internal)

    def render(self, entry: PagePlanEntry, max_pixels: int = 800) -> fitz.Pixmap:
        if entry.source_kind == "blank":
            with fitz.open() as single:
                self.append(single, entry)
                page = single[0]
                scale = max_pixels / max(page.rect.width, page.rect.height)
                return page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        # Keep the entire source resource context, including optional-content
        # configuration, inherited resources and original widget appearances.
        # insert_pdf into a new one-page PDF can change those appearances.
        key = (entry.source_path, entry.password) if entry.source_kind == "external" else ("current", "")
        if key not in self._previews:
            self._previews[key] = fitz.open(
                stream=self.source(entry).tobytes(garbage=0, deflate=False, clean=False, no_new_id=True),
                filetype="pdf",
            )
        page = self._previews[key][entry.source_page]
        original_box, original_rotation = page.cropbox, page.rotation
        try:
            apply_transform(page, entry)
            scale = max_pixels / max(page.rect.width, page.rect.height)
            return page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        finally:
            if page.cropbox != original_box:
                page.set_cropbox(original_box)
            if page.rotation != original_rotation:
                page.set_rotation(original_rotation)

    def close(self):
        for source in self.sources.values():
            source.close()
        self.sources.clear()
        for preview in self._previews.values():
            preview.close()
        self._previews.clear()
        for source in self._copy_sources.values():
            source.close()
        self._copy_sources.clear()
        self._ocg_tags.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def crop_entries(entries: list[PagePlanEntry], positions: Iterable[int], margins_mm: tuple[float, float, float, float],
                 reader: PlanReader) -> list[PagePlanEntry]:
    """Margins are left/top/right/bottom in the displayed (rotated) frame."""
    if not all(math.isfinite(v) and v >= 0 for v in margins_mm):
        raise ValueError("Crop margins must be non-negative finite values.")
    result = entries.copy()
    failures = []
    for index in sorted(set(positions)):
        entry = entries[index]
        left, top, right, bottom = (v * POINTS_PER_MM for v in margins_mm)
        rotation = entry.final_rotation % 360
        if rotation == 90:
            left, top, right, bottom = top, right, bottom, left
        elif rotation == 180:
            left, top, right, bottom = right, bottom, left, top
        elif rotation == 270:
            left, top, right, bottom = bottom, left, top, right
        box = reader.box(entry)
        crop = fitz.Rect(box.x0 + left, box.y0 + top, box.x1 - right, box.y1 - bottom)
        if crop.width <= 0.01 or crop.height <= 0.01:
            failures.append(index + 1)
        else:
            result[index] = replace(entry, crop_box=tuple(crop))
    if failures:
        raise ValueError("Crop leaves no visible area on pages: " + ", ".join(map(str, failures)))
    return result


def apply_plan_to_document(doc: fitz.Document, entries: Iterable[PagePlanEntry], *, cancelled=lambda: False,
                           progress=lambda *_: None) -> None:
    """Shared assembly, mutating doc; caller provides rollback or a private copy."""
    plan = list(entries)
    if not plan or len({entry.entry_id for entry in plan}) != len(plan):
        raise ValueError("A page plan needs at least one page and unique page identities.")
    if any(entry.final_rotation % 90 for entry in plan):
        raise ValueError("Page rotation must be a multiple of 90 degrees.")
    if len(plan) == doc.page_count and all(
        entry.source_kind == "current" and entry.source_page == index
        for index, entry in enumerate(plan)
    ):
        # Rotation/crop alone must not rebuild the page tree or copy page
        # objects: original streams, resources, appearances and xrefs stay put.
        for index, entry in enumerate(plan):
            if cancelled():
                raise InterruptedError("Page operation cancelled.")
            apply_transform(doc[index], entry)
            progress(index + 1, len(plan))
        return
    # Retain the first original page object; every duplicate is independently
    # inserted from an immutable source so edits never leak between copies.
    with fitz.open(stream=doc.tobytes(), filetype="pdf") as original, PlanReader(original) as reader:
        for entry in plan:
            if entry.final_rotation % 90:
                raise ValueError("Page rotation must be a multiple of 90 degrees.")
            if entry.source_kind != "blank":
                source = reader.source(entry)
                if not 0 <= entry.source_page < source.page_count:
                    raise ValueError("Page plan references an invalid source page.")
        seen = set()
        desired = []
        for index, entry in enumerate(plan):
            if cancelled():
                raise InterruptedError("Page operation cancelled.")
            if entry.source_kind == "current" and entry.source_page not in seen:
                desired.append(entry.source_page)
                seen.add(entry.source_page)
            else:
                desired.append(doc.page_count)
                reader.append(doc, entry)
            progress(index + 1, len(plan))
        doc.select(desired)
        for index, entry in enumerate(plan):
            apply_transform(doc[index], entry)


class SourceStore:
    """Owned snapshots survive dialog acceptance until Apply has finished."""

    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pdfdocuedit-organizer-")
        self.originals: set[Path] = set()

    def snapshot(self, path: str, password: str = "", *, cancelled=lambda: False, progress=lambda *_: None) -> tuple[str, list[int]]:
        original = Path(path).resolve()
        target = Path(self.temporary.name) / f"{uuid.uuid4().hex}.pdf"
        try:
            total, done = original.stat().st_size, 0
            with original.open("rb") as source, target.open("xb") as output:
                while block := source.read(1024 * 1024):
                    if cancelled():
                        raise InterruptedError("Import cancelled.")
                    output.write(block)
                    done += len(block)
                    progress(done, total)
            with fitz.open(target) as document:
                if document.needs_pass and not document.authenticate(password):
                    raise ValueError("The source PDF password is not valid.")
                rotations = []
                for page in document:
                    if cancelled():
                        raise InterruptedError("Import cancelled.")
                    rotations.append(page.rotation)
            if cancelled():
                raise InterruptedError("Import cancelled.")
            self.originals.add(original)
            return str(target), rotations
        except Exception:
            target.unlink(missing_ok=True)
            raise

    def discard(self, snapshot):
        path = Path(snapshot).resolve()
        if path.parent != Path(self.temporary.name).resolve():
            raise ValueError("Snapshot is outside the managed source store.")
        path.unlink(missing_ok=True)

    def close(self):
        self.temporary.cleanup()


@dataclass
class ExportResult:
    completed: list[Path]
    error: str = ""
    cancelled: bool = False


def export_plan(current_bytes: bytes, jobs: list[tuple[Path, list[PagePlanEntry]]], *, protected: Iterable[Path] = (),
                overwrite=False, cancelled=lambda: False, progress=lambda *_: None) -> ExportResult:
    result = ExportResult([])
    targets = [path.resolve() for path, _ in jobs]
    protected = {path.resolve() for path in protected}
    try:
        if len(targets) != len(set(targets)):
            raise ValueError("Output filenames must be distinct.")
        for path in targets:
            if path in protected or any(path.exists() and other.exists() and path.samefile(other) for other in protected):
                raise ValueError("Choose a new output file instead of an open/source PDF.")
            if path.exists() and not overwrite:
                raise ValueError(f"Output already exists: {path.name}")
        for number, (target, plan) in enumerate(jobs):
            if cancelled():
                raise InterruptedError("Export cancelled.")
            with fitz.open(stream=current_bytes, filetype="pdf") as output:
                apply_plan_to_document(output, plan, cancelled=cancelled,
                                       progress=lambda done, total, number=number: progress(number * 1000 + round(done * 1000 / total), len(jobs) * 1000))
                with atomic_output(target, overwrite=overwrite) as staged:
                    output.save(staged, garbage=1, deflate=False, clean=False)
                    validate_pdf_file(staged, expected_page_count=len(plan))
                    if cancelled():
                        raise InterruptedError("Export cancelled.")
                    if target.exists() and not overwrite:
                        raise ValueError(f"Output appeared during export: {target.name}")
            result.completed.append(target)
            progress((number + 1) * 1000, len(jobs) * 1000)
    except InterruptedError as exc:
        result.cancelled, result.error = True, str(exc)
    except Exception as exc:
        log_failure('page_plan.export_plan: fallback after failure', 10)
        result.error = str(exc)
    return result
