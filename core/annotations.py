"""Pure PyMuPDF annotation and content-editing operations (no Qt imports)."""

from __future__ import annotations

import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import fitz

from .pdf_engine import DOCUMENT_LOCK

STAMP_IDS: dict[str, int] = {
    "Approved": 0,
    "AsIs": 1,
    "Confidential": 2,
    "Departmental": 3,
    "Experimental": 4,
    "Expired": 5,
    "Final": 6,
    "ForComment": 7,
    "ForPublicRelease": 8,
    "NotApproved": 9,
    "NotForPublicRelease": 10,
    "Sold": 11,
    "TopSecret": 12,
    "Draft": 13,
}

ANNOT_COLORS: dict[str, tuple[float, float, float]] = {
    "yellow": (1.0, 0.83, 0.35),
    "green": (0.5, 0.8, 0.45),
    "cyan": (0.3, 0.82, 0.88),
    "pink": (0.95, 0.56, 0.7),
    "orange": (1.0, 0.72, 0.45),
    "red": (0.9, 0.45, 0.45),
}

DEFAULT_COLOR = "yellow"


@dataclass(frozen=True)
class AnnotationOp:
    """One annotation action collected by the canvas and applied by the viewer."""

    kind: str
    page: int
    rects: tuple[fitz.Rect, ...] = ()
    points: tuple[tuple[float, float], ...] = ()
    text: str = ""
    color: str = DEFAULT_COLOR
    width: float = 1.5
    stamp_kind: str = "Draft"
    image_path: str = ""

    def description(self) -> str:
        labels = {
            "highlight": "Highlight",
            "underline": "Underline",
            "strikeout": "Strikeout",
            "squiggly": "Squiggly",
            "note": "Note",
            "ink": "Freehand",
            "rect": "Rectangle",
            "line": "Line",
            "circle": "Circle",
            "polygon": "Polygon",
            "redact": "Redact",
            "stamp": "Stamp",
            "image": "Image",
        }
        return labels.get(self.kind, self.kind.title())


def _quads(rects: Iterable[fitz.Rect]) -> list[fitz.Quad]:
    return [rect.quad for rect in rects]


def _rgb(color: str) -> tuple[float, float, float]:
    return ANNOT_COLORS.get(color, ANNOT_COLORS[DEFAULT_COLOR])


def _page(doc: fitz.Document, page_num: int) -> fitz.Page:
    return doc.load_page(page_num)


def add_highlight(
    doc: fitz.Document,
    page_num: int,
    rects: Sequence[fitz.Rect],
    color: str = DEFAULT_COLOR,
) -> None:
    page = _page(doc, page_num)
    annot = page.add_highlight_annot(quads=_quads(rects))
    annot.set_colors(stroke=_rgb(color))
    annot.update()


def add_underline(
    doc: fitz.Document,
    page_num: int,
    rects: Sequence[fitz.Rect],
    color: str = DEFAULT_COLOR,
) -> None:
    page = _page(doc, page_num)
    annot = page.add_underline_annot(quads=_quads(rects))
    annot.set_colors(stroke=_rgb(color))
    annot.update()


def add_strikeout(
    doc: fitz.Document,
    page_num: int,
    rects: Sequence[fitz.Rect],
    color: str = DEFAULT_COLOR,
) -> None:
    page = _page(doc, page_num)
    annot = page.add_strikeout_annot(quads=_quads(rects))
    annot.set_colors(stroke=_rgb(color))
    annot.update()


def add_squiggly(
    doc: fitz.Document,
    page_num: int,
    rects: Sequence[fitz.Rect],
    color: str = DEFAULT_COLOR,
) -> None:
    page = _page(doc, page_num)
    annot = page.add_squiggly_annot(quads=_quads(rects))
    annot.set_colors(stroke=_rgb(color))
    annot.update()


def add_note(
    doc: fitz.Document,
    page_num: int,
    point: tuple[float, float],
    text: str,
    icon: str = "Note",
) -> None:
    page = _page(doc, page_num)
    annot = page.add_text_annot(fitz.Point(point), text, icon=icon)
    annot.update()


def add_ink(
    doc: fitz.Document,
    page_num: int,
    points: Sequence[tuple[float, float]],
    color: str = "red",
    width: float = 1.5,
) -> None:
    page = _page(doc, page_num)
    annot = page.add_ink_annot([list(points)])
    annot.set_border(width=width)
    annot.set_colors(stroke=_rgb(color))
    annot.update()


def add_rect(
    doc: fitz.Document,
    page_num: int,
    rect: fitz.Rect,
    color: str = "red",
    width: float = 1.5,
) -> None:
    page = _page(doc, page_num)
    annot = page.add_rect_annot(rect)
    annot.set_border(width=width)
    annot.set_colors(stroke=_rgb(color))
    annot.update()


def add_line(
    doc: fitz.Document,
    page_num: int,
    p1: tuple[float, float],
    p2: tuple[float, float],
    color: str = "red",
    width: float = 1.5,
) -> None:
    page = _page(doc, page_num)
    annot = page.add_line_annot(fitz.Point(p1), fitz.Point(p2))
    annot.set_border(width=width)
    annot.set_colors(stroke=_rgb(color))
    annot.update()


def add_circle(
    doc: fitz.Document,
    page_num: int,
    rect: fitz.Rect,
    color: str = "red",
    width: float = 1.5,
) -> None:
    page = _page(doc, page_num)
    annot = page.add_circle_annot(rect)
    annot.set_border(width=width)
    annot.set_colors(stroke=_rgb(color))
    annot.update()


def add_polygon(
    doc: fitz.Document,
    page_num: int,
    points: Sequence[tuple[float, float]],
    color: str = "red",
    width: float = 1.5,
) -> None:
    page = _page(doc, page_num)
    annot = page.add_polygon_annot(list(points))
    annot.set_border(width=width)
    annot.set_colors(stroke=_rgb(color))
    annot.update()


def add_stamp(
    doc: fitz.Document,
    page_num: int,
    rect: fitz.Rect,
    stamp_kind: str = "Draft",
) -> None:
    page = _page(doc, page_num)
    annot = page.add_stamp_annot(
        rect, stamp=STAMP_IDS.get(stamp_kind, STAMP_IDS["Draft"])
    )
    annot.update()


def redact(doc: fitz.Document, page_num: int, rects: Sequence[fitz.Rect]) -> None:
    page = _page(doc, page_num)
    for rect in rects:
        page.add_redact_annot(rect)
    page.apply_redactions()


def insert_image(
    doc: fitz.Document,
    page_num: int,
    rect: fitz.Rect,
    image_path: str | Path,
) -> None:
    with DOCUMENT_LOCK:
        _page(doc, page_num).insert_image(rect, filename=str(image_path), overlay=True)


def list_annotations(page: fitz.Page) -> list[dict]:
    """Return lightweight descriptions of all annotations on a page.

    Page operations (delete/insert/reorder) rebuild page objects, which can
    leave stale annotation xrefs behind; such entries are skipped instead of
    crashing the UI.
    """
    results: list[dict] = []
    try:
        for index, annot in enumerate(page.annots()):
            try:
                kind = str(annot.type[1])
                rect = annot.rect
            except Exception:
                continue  # stale xref after a page rebuild
            results.append({"kind": kind, "rect": rect, "index": index})
    except Exception:
        pass  # the annotation list itself is stale
    return results


def remove_annotation(page: fitz.Page, index: int) -> None:
    with DOCUMENT_LOCK:
        try:
            annots = list(page.annots())
        except Exception:
            return  # stale annotation list after a page rebuild
        if 0 <= index < len(annots):
            try:
                page.delete_annot(annots[index])
            except Exception:
                pass  # the xref vanished mid-operation


def apply_annotation(doc: fitz.Document, op: AnnotationOp) -> None:
    """Apply one AnnotationOp to the live document (serialized against renders)."""
    with DOCUMENT_LOCK:
        if op.kind in {"highlight", "underline", "strikeout", "squiggly"}:
            handler = {
                "highlight": add_highlight,
                "underline": add_underline,
                "strikeout": add_strikeout,
                "squiggly": add_squiggly,
            }[op.kind]
            handler(doc, op.page, list(op.rects), op.color)
        elif op.kind == "note":
            add_note(doc, op.page, op.points[0] if op.points else (0, 0), op.text)
        elif op.kind == "ink":
            add_ink(doc, op.page, op.points, op.color, op.width)
        elif op.kind == "rect":
            add_rect(doc, op.page, op.rects[0], op.color, op.width)
        elif op.kind == "line":
            add_line(doc, op.page, op.points[0], op.points[1], op.color, op.width)
        elif op.kind == "circle":
            add_circle(doc, op.page, op.rects[0], op.color, op.width)
        elif op.kind == "polygon":
            add_polygon(doc, op.page, op.points, op.color, op.width)
        elif op.kind == "stamp":
            add_stamp(doc, op.page, op.rects[0], op.stamp_kind)
        elif op.kind == "redact":
            redact(doc, op.page, list(op.rects))
        elif op.kind == "image":
            insert_image(doc, op.page, op.rects[0], op.image_path)
        else:
            raise ValueError(f"Unknown annotation kind: {op.kind}")


# --- watermarks ----------------------------------------------------------
def _watermark_font(size: int):
    from PIL import ImageFont

    candidates = (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf",
    )
    for candidate in candidates:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _render_watermark_text_png(
    text: str,
    fontsize: int,
    opacity: float,
    rotation: float,
    color: tuple[float, float, float],
) -> Path:
    from PIL import Image, ImageDraw

    font = _watermark_font(fontsize)
    probe = Image.new("RGBA", (8, 8))
    left, top, right, bottom = ImageDraw.Draw(probe).textbbox((0, 0), text, font=font)
    width = max(1, right - left + 32)
    height = max(1, bottom - top + 32)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    alpha = max(0, min(255, round(opacity * 255)))
    rgb = tuple(max(0, min(255, round(channel * 255))) for channel in color)
    draw.text((16 - left, 16 - top), text, font=font, fill=(*rgb, alpha))
    if rotation:
        image = image.rotate(rotation, expand=True, resample=Image.BICUBIC)
    handle, path = tempfile.mkstemp(suffix=".png", prefix="pdfdocuedit-watermark-")
    import os

    os.close(handle)
    image.save(path)
    return Path(path)


def _image_with_opacity_png(image_path: str | Path, opacity: float) -> Path:
    from PIL import Image

    with Image.open(image_path).convert("RGBA") as source:
        alpha = max(0, min(255, round(opacity * 255)))
        if source.mode == "RGBA":
            r, g, b, a = source.split()
            a = a.point(lambda value: min(value, alpha))
            result = Image.merge("RGBA", (r, g, b, a))
        else:
            result = source.convert("RGBA")
            result.putalpha(alpha)
        handle, path = tempfile.mkstemp(suffix=".png", prefix="pdfdocuedit-watermark-")
        import os

        os.close(handle)
        result.save(path)
    return Path(path)


def _insert_image_fit(
    page: fitz.Page,
    png_path: Path,
    scale: float = 0.6,
) -> None:
    pixmap = fitz.Pixmap(str(png_path))
    width, height = pixmap.width, pixmap.height
    pixmap = None
    rect = page.rect
    factor = min(rect.width * scale / width, rect.height * scale / height)
    target_w = width * factor
    target_h = height * factor
    target = fitz.Rect(
        (rect.width - target_w) / 2,
        (rect.height - target_h) / 2,
        (rect.width + target_w) / 2,
        (rect.height + target_h) / 2,
    )
    page.insert_image(target, filename=str(png_path), overlay=True)


def add_watermark_text(
    doc: fitz.Document,
    pages: Sequence[int],
    text: str,
    fontsize: int = 64,
    opacity: float = 0.25,
    rotation: float = 45.0,
    color: tuple[float, float, float] = (0.5, 0.5, 0.5),
) -> None:
    png = _render_watermark_text_png(text, fontsize, opacity, rotation, color)
    try:
        with DOCUMENT_LOCK:
            for page_num in pages:
                if 0 <= page_num < doc.page_count:
                    _insert_image_fit(doc.load_page(page_num), png)
    finally:
        png.unlink(missing_ok=True)


def add_watermark_image(
    doc: fitz.Document,
    pages: Sequence[int],
    image_path: str | Path,
    opacity: float = 0.25,
    scale: float = 0.4,
) -> None:
    png = _image_with_opacity_png(image_path, opacity)
    try:
        with DOCUMENT_LOCK:
            for page_num in pages:
                if 0 <= page_num < doc.page_count:
                    _insert_image_fit(doc.load_page(page_num), png, scale)
    finally:
        png.unlink(missing_ok=True)
