"""PDF-on-PDF overlay geometry, page pairing, preflight, and preview."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import fitz

MM_TO_PT = 72.0 / 25.4
PageMapping = Literal["repeat_last", "cycle", "matching_only"]
ScaleMode = Literal["fit", "actual"]
Alignment = Literal[
    "top-left", "top", "top-right", "left", "center", "right",
    "bottom-left", "bottom", "bottom-right",
]


@dataclass(frozen=True)
class OverlayOptions:
    mapping: PageMapping = "repeat_last"
    layer: Literal["foreground", "background"] = "foreground"
    scale_mode: ScaleMode = "fit"
    alignment: Alignment = "center"
    rotation: int = 0
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0

    def __post_init__(self) -> None:
        if self.mapping not in {"repeat_last", "cycle", "matching_only"}:
            raise ValueError("Invalid overlay page mapping")
        if self.layer not in {"foreground", "background"}:
            raise ValueError("Invalid overlay layer")
        if self.scale_mode not in {"fit", "actual"}:
            raise ValueError("Invalid overlay scale mode")
        if self.alignment not in {
            "top-left", "top", "top-right", "left", "center", "right",
            "bottom-left", "bottom", "bottom-right",
        }:
            raise ValueError("Invalid overlay alignment")
        if self.rotation not in {0, 90, 180, 270}:
            raise ValueError("Overlay rotation must be 0, 90, 180, or 270 degrees")
        if not all(math.isfinite(value) for value in (self.offset_x_mm, self.offset_y_mm)):
            raise ValueError("Overlay offsets must be finite")


@dataclass(frozen=True)
class OverlayJob:
    source: Path
    output: Path
    pages: int
    problem: str = ""


@dataclass(frozen=True)
class OverlayFileResult:
    source: Path
    output: Path
    status: Literal["completed", "failed", "skipped"]
    detail: str = ""


@dataclass(frozen=True)
class OverlayPreflight:
    template_pages: int
    jobs: tuple[OverlayJob, ...]

    @property
    def valid(self) -> bool:
        return self.template_pages > 0 and bool(self.jobs) and all(not job.problem for job in self.jobs)


def scan_overlay_inputs(template_path: Path, sources: list[Path], output_folder: Path,
                        suffix: str, overwrite: bool,
                        source_overrides: dict[Path, Path] | None = None,
                        is_cancelled: Callable[[], bool] | None = None) -> OverlayPreflight:
    """Inspect a fixed batch before writing any output file."""
    template_path = template_path.expanduser().resolve()
    output_folder = output_folder.expanduser().resolve()
    if not output_folder.is_dir():
        raise ValueError("Choose an existing output folder")
    try:
        with fitz.open(template_path) as template:
            if template.needs_pass or template.page_count == 0:
                raise ValueError("Template PDF is encrypted or empty")
            template_pages = template.page_count
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"Cannot read the template PDF: {exc}") from exc
    overrides = {key.resolve(): value for key, value in (source_overrides or {}).items()}
    seen: set[str] = set()
    jobs = []
    for item in sources:
        if is_cancelled and is_cancelled():
            raise InterruptedError("Overlay preflight cancelled")
        source = item.expanduser().resolve()
        output = source if overwrite and not suffix else output_folder / f"{source.stem}{suffix}.pdf"
        problem = ""
        pages = 0
        output_key = str(output).casefold()
        if source == template_path:
            problem = "Template cannot also be a target"
        elif output.resolve() == template_path:
            problem = "Output would overwrite the template"
        elif output_key in seen:
            problem = "Another target has the same output filename"
        elif output == source and not overwrite:
            problem = "Output would overwrite its source"
        elif output.exists() and not overwrite:
            problem = "Output already exists"
        elif not source.is_file() or source.suffix.casefold() != ".pdf":
            problem = "Target is not a readable PDF file"
        seen.add(output_key)
        if not problem:
            try:
                with fitz.open(overrides.get(source, source)) as document:
                    if document.needs_pass or document.page_count == 0:
                        problem = "Target PDF is encrypted or empty"
                    else:
                        pages = document.page_count
            except (OSError, RuntimeError) as exc:
                problem = f"Cannot read target PDF: {exc}"
        jobs.append(OverlayJob(source, output, pages, problem))
    return OverlayPreflight(template_pages, tuple(jobs))


def template_page_number(target_page: int, template_pages: int, mapping: PageMapping) -> int | None:
    if template_pages < 1 or target_page < 0:
        raise ValueError("Page numbers must be non-negative and the template must have pages")
    if mapping == "repeat_last":
        return min(target_page, template_pages - 1)
    if mapping == "cycle":
        return target_page % template_pages
    if mapping == "matching_only":
        return target_page if target_page < template_pages else None
    raise ValueError("Invalid overlay page mapping")


def destination_rect(target_rect: fitz.Rect, source_rect: fitz.Rect, options: OverlayOptions) -> fitz.Rect:
    width, height = source_rect.width, source_rect.height
    if options.rotation in {90, 270}:
        width, height = height, width
    if width <= 0 or height <= 0 or target_rect.is_empty:
        raise ValueError("Cannot overlay an empty PDF page")
    if options.scale_mode == "fit":
        factor = min(target_rect.width / width, target_rect.height / height)
        width *= factor
        height *= factor
    horizontal = options.alignment.split("-")[-1]
    vertical = options.alignment.split("-")[0]
    if options.alignment in {"top", "center", "bottom"}:
        horizontal = "center"
    if options.alignment in {"left", "right"}:
        vertical = "center"
    x = {"left": target_rect.x0, "center": target_rect.x0 + (target_rect.width - width) / 2,
         "right": target_rect.x1 - width}[horizontal]
    y = {"top": target_rect.y0, "center": target_rect.y0 + (target_rect.height - height) / 2,
         "bottom": target_rect.y1 - height}[vertical]
    x += options.offset_x_mm * MM_TO_PT
    y += options.offset_y_mm * MM_TO_PT
    return fitz.Rect(x, y, x + width, y + height)


def apply_overlay_page(page: fitz.Page, template: fitz.Document, page_number: int,
                       options: OverlayOptions) -> bool:
    source_number = template_page_number(page_number, template.page_count, options.mapping)
    if source_number is None:
        return False
    source = template.load_page(source_number)
    rect = destination_rect(page.rect, source.rect, options)
    page.show_pdf_page(
        rect, template, source_number, overlay=options.layer == "foreground",
        keep_proportion=True, rotate=options.rotation,
    )
    return True


def render_overlay_preview(template_path: Path, target_path: Path, page_number: int,
                           options: OverlayOptions, max_dimension: int = 1100) -> tuple[bytes, bytes, int]:
    """Render before and after from the same PDF operation used by export."""
    with fitz.open(target_path) as target, fitz.open(template_path) as template:
        if target.needs_pass or template.needs_pass or not target.page_count or not template.page_count:
            raise ValueError("Preview needs readable PDFs with at least one page")
        page_number = max(0, min(page_number, target.page_count - 1))
        page = target.load_page(page_number)
        zoom = min(1.5, max_dimension / max(page.rect.width, page.rect.height))
        before = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).tobytes("png")
        with fitz.open() as preview:
            preview.insert_pdf(target, from_page=page_number, to_page=page_number)
            result = preview.load_page(0)
            apply_overlay_page(result, template, page_number, options)
            after = result.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).tobytes("png")
        return before, after, target.page_count
