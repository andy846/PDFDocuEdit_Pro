"""Declarative page-aware PDF merge and portable list persistence (no Qt)."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import fitz

from .measurement import copy_page_scales
from .pdf_io import set_safe_pdf_metadata, validate_pdf_file


@dataclass
class MergeItem:
    path: str
    pages: list[int] | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    identity: dict = field(default_factory=dict)
    label: str = ""


@dataclass
class MergeSpec:
    items: list[MergeItem]
    output_path: str
    compact: bool = False
    protected_paths: list[str] = field(default_factory=list)


@dataclass
class MergeResult:
    output_path: Path
    page_count: int
    page_map: list[dict]
    warnings: list[str]


def natural_key(value):
    return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                 for part in re.split(r"(\d+)", str(value)))


def strict_pages(text: str, count: int) -> list[int]:
    """Unlike the legacy parser, never truncate an invalid range silently."""
    from .tools import ToolError
    value = text.strip().casefold()
    if value in ("all", "odd", "even"):
        pages = list(range(count)) if value == "all" else list(range(0 if value == "odd" else 1, count, 2))
    else:
        pages = set()
        for part in value.split(","):
            match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", part)
            if not match:
                raise ToolError("Use page numbers such as 1,3,5-8, All, Odd or Even.")
            start, end = int(match[1]), int(match[2] or match[1])
            if not 1 <= start <= end <= count:
                raise ToolError(f"Page range {part.strip()} is outside 1–{count} or reversed.")
            pages.update(range(start-1, end))
        pages = sorted(pages)
    if not pages:
        raise ToolError("Select at least one page.")
    return list(pages)


def inspect_merge_source(path):
    stat = os.stat(path)
    with fitz.open(path) as pdf:
        if pdf.needs_pass:
            raise ValueError("Password required — open/unlock this PDF before adding a snapshot.")
        if not pdf.page_count:
            raise ValueError("PDF has no pages.")
        return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "pages": pdf.page_count,
                "signed": pdf.get_sigflags() > 0}


def merge_pdf_items(spec: MergeSpec, progress=None, is_cancelled=None) -> MergeResult:
    from .tools import ToolError, _temporary_pdf_path
    def checkpoint():
        if is_cancelled and is_cancelled():
            raise ToolError("The merge was cancelled.")
    def report(done, total, message):
        checkpoint()
        if progress:
            progress(done, total, message)
    if not spec.items:
        raise ToolError("Add at least one PDF.")
    target = Path(spec.output_path).expanduser().resolve()
    sources = [Path(item.path).expanduser().resolve() for item in spec.items]
    if target in sources or target in [Path(p).expanduser().resolve() for p in spec.protected_paths]:
        raise ToolError("Output cannot replace a source or an open PDF. Choose a different filename.")
    prepared, expected, warnings = [], 0, []
    total = len(sources)*2+2
    for index, (item, path) in enumerate(zip(spec.items, sources, strict=True)):
        report(index, total, f"Checking {item.label or path.name}")
        try:
            stat = os.stat(path)
            identity = item.identity or {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "pages": None, "signed": False}
            if stat.st_size != identity["size"] or stat.st_mtime_ns != identity["mtime_ns"]:
                raise ToolError("Source changed. Recheck and confirm page selection.")
            if item.identity and any(identity[key] != item.identity.get(key) for key in ("size", "mtime_ns", "pages")):
                raise ToolError("Source changed. Recheck and confirm page selection.")
            pages = item.pages
            if pages is not None and (not pages or any(type(p) is not int or p < 0 or
                    (identity["pages"] is not None and p >= identity["pages"]) for p in pages)
                    or pages != sorted(set(pages))):
                raise ToolError("Invalid selected pages. Review this source.")
            prepared.append((item, path, identity, pages))
        except Exception as exc:
            raise ToolError(f"Cannot read {item.label or path.name}: {exc}") from exc
    temporary = _temporary_pdf_path(target)
    page_map = []
    try:
        with fitz.open() as output:
            metadata = None
            for index, (item, path, identity, pages) in enumerate(prepared):
                report(len(sources)+index, total, f"Merging {item.label or path.name}")
                try:
                    stat = os.stat(path)
                    if stat.st_size != identity["size"] or stat.st_mtime_ns != identity["mtime_ns"]:
                        raise ToolError("Source changed during preparation.")
                    with fitz.open(path) as source:
                        if source.needs_pass or (identity["pages"] is not None and source.page_count != identity["pages"]):
                            raise ToolError("Source page count or password changed. Recheck the source.")
                        pages = list(range(source.page_count)) if pages is None else pages
                        if any(p >= source.page_count for p in pages) or not pages:
                            raise ToolError("Invalid selected pages. Review this source.")
                        expected += len(pages)
                        if source.get_sigflags() > 0:
                            warnings.append(f"{item.label or path.name}: merging does not preserve signature validity.")
                        if metadata is None:
                            metadata = source.metadata
                        start = output.page_count
                        mapping = {page: start+i for i, page in enumerate(pages)}
                        whole = pages == list(range(source.page_count))
                        # Contiguous runs keep insertion efficient; rebuild links across runs.
                        runs = []
                        for page in pages:
                            if runs and page == runs[-1][1]+1:
                                runs[-1][1] = page
                            else:
                                runs.append([page, page])
                        if whole:
                            output.insert_pdf(source)
                        else:
                            for first, last in runs:
                                checkpoint()
                                output.insert_pdf(source, from_page=first, to_page=last, links=False)
                        copy_page_scales(source, output, pages, start)
                        excluded_links = 0
                        for page in pages:
                            checkpoint()
                            for original in ([] if whole else source[page].get_links()):
                                link = {k: v for k, v in original.items() if k not in ("xref", "id")}
                                if link["kind"] == fitz.LINK_GOTO:
                                    if link.get("page") not in mapping:
                                        excluded_links += 1
                                        continue
                                    link["page"] = mapping[link["page"]]
                                output[mapping[page]].insert_link(link)
                            page_map.append({"output_page": mapping[page]+1, "item_id": item.id,
                                             "source_file": item.label or str(path), "source_page": page+1})
                        if excluded_links:
                            warnings.append(f"{item.label or path.name}: removed {excluded_links} internal link(s) to excluded pages.")
                except Exception as exc:
                    raise ToolError(f"Cannot read {item.label or path.name}: {exc}") from exc
            if metadata:
                set_safe_pdf_metadata(output, metadata)
            report(total-2, total, "Saving merged PDF…")
            output.save(temporary, garbage=4 if spec.compact else 1, deflate=spec.compact)
        report(total-1, total, "Validating merged PDF…")
        validate_pdf_file(temporary, expected_page_count=expected)
        checkpoint()
        os.replace(temporary, target)
        if progress:
            progress(total, total, "Complete")
        return MergeResult(target, expected, page_map, warnings)
    finally:
        temporary.unlink(missing_ok=True)


def export_merge_map(result, path):
    with Path(path).open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=["output_page", "item_id", "source_file", "source_page"])
        writer.writeheader()
        writer.writerows(result.page_map)


def _write_json(path, raw):
    from .io_atomic import atomic_output
    with atomic_output(path) as staging:
        staging.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")


def save_merge_list(path, entries, output_path="", compact=False):
    """Snapshot assets are content-addressed; disk sources remain references."""
    path = Path(path).resolve()
    raw_entries = []
    for entry in entries:
        raw = {key: entry[key] for key in ("id", "path", "label", "selection", "snapshot", "added", "identity")}
        if entry.get("original_path"):
            raw["original_path"] = entry["original_path"]
        raw["review_required"] = bool(entry.get("review_required", False))
        source = Path(raw["path"])
        if raw["snapshot"]:
            assets = path.with_suffix(".assets")
            assets.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            asset = assets / f"{digest}.pdf"
            if asset.exists():
                with asset.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                        raise ValueError("Existing snapshot asset is corrupt. Restore the assets folder.")
            if not asset.exists():
                staging = assets / f".{uuid.uuid4().hex}.tmp"
                try:
                    shutil.copyfile(source, staging)
                    os.replace(staging, asset)
                finally:
                    staging.unlink(missing_ok=True)
            raw["path"] = os.path.relpath(asset, path.parent)
            raw["digest"] = digest
            raw["identity"] = inspect_merge_source(asset)
        else:
            try:
                raw["path"] = os.path.relpath(source, path.parent)
            except ValueError:
                raw["path"] = str(source)
        raw_entries.append(raw)
    _write_json(path, {"merge_version": 1, "items": raw_entries, "output_path": output_path, "compact": compact})
    return path


def load_merge_list(path):
    from .tools import ToolError
    path = Path(path).resolve()
    if path.stat().st_size > 16*1024*1024:
        raise ToolError("Merge list exceeds 16 MB.")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(raw, dict) or raw.get("merge_version") != 1 or not isinstance(raw.get("items"), list)
            or len(raw["items"]) > 100000 or type(raw.get("compact")) is not bool or not isinstance(raw.get("output_path"), str)):
        raise ToolError("Invalid or unsupported merge list.")
    ids = set()
    for entry in raw["items"]:
        if (not isinstance(entry, dict) or any(not isinstance(entry.get(key), str) for key in ("id", "path", "label", "selection"))
                or not isinstance(entry.get("identity"), dict) or type(entry.get("snapshot")) is not bool
                or type(entry.get("added")) is not int or entry["id"] in ids or not entry["path"].lower().endswith(".pdf")):
            raise ToolError("Invalid merge list item.")
        if (any(len(entry[key]) > 4096 for key in ("id", "path", "label", "selection"))
                or not isinstance(entry.get("original_path", ""), str)
                or type(entry.get("review_required", False)) is not bool
                or ("digest" in entry and (not isinstance(entry["digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["digest"])))):
            raise ToolError("Invalid merge list source metadata.")
        ids.add(entry["id"])
        entry["path"] = os.path.abspath(os.path.join(path.parent, entry["path"]))
        entry["status"], entry["error"] = "Checking", ""
    return raw
