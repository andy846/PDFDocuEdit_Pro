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
class AnnotationStyle:
    stroke: str = DEFAULT_COLOR
    fill: str = ""
    opacity: float = 1.0
    width: float = 1.5
    font: str = "Helv"
    font_size: float = 11.0
    alignment: int = 0


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
    style: AnnotationStyle | None = None

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
            "arrow": "Arrow",
            "circle": "Circle",
            "ellipse": "Ellipse",
            "polygon": "Polygon",
            "freetext_typewriter": "Typewriter Text",
            "freetext_box": "Text Box",
            "freetext_callout": "Callout",
            "redact": "Redact",
            "stamp": "Stamp",
            "signature": "Signature",
            "image": "Image",
        }
        return labels.get(self.kind, self.kind.title())


def _quads(rects: Iterable[fitz.Rect]) -> list[fitz.Quad]:
    return [rect.quad for rect in rects]


def _rgb(color: str) -> tuple[float, float, float]:
    value = str(color).strip()
    if value.startswith("#") and len(value) == 7:
        try:
            return tuple(
                int(value[index : index + 2], 16) / 255.0 for index in (1, 3, 5)
            )
        except ValueError:
            pass
    return ANNOT_COLORS.get(value, ANNOT_COLORS[DEFAULT_COLOR])


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


def add_arrow(
    doc: fitz.Document,
    page_num: int,
    p1: tuple[float, float],
    p2: tuple[float, float],
    style: AnnotationStyle,
) -> None:
    page = _page(doc, page_num)
    annot = page.add_line_annot(fitz.Point(p1), fitz.Point(p2))
    annot.set_border(width=style.width)
    annot.set_colors(stroke=_rgb(style.stroke))
    annot.set_line_ends(fitz.PDF_ANNOT_LE_NONE, fitz.PDF_ANNOT_LE_OPEN_ARROW)
    annot.set_opacity(max(0.0, min(1.0, style.opacity)))
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


def add_freetext(
    doc: fitz.Document,
    page_num: int,
    rect: fitz.Rect,
    text: str,
    style: AnnotationStyle,
    *,
    callout: Sequence[tuple[float, float]] = (),
    boxed: bool = False,
) -> None:
    page = _page(doc, page_num)
    callout_points = (
        [fitz.Point(point) for point in callout] if len(callout) == 3 else None
    )
    callout_options: dict[str, object] = {}
    if callout_points:
        callout_options = {
            "callout": callout_points,
            "line_end": fitz.PDF_ANNOT_LE_OPEN_ARROW,
        }
    annot = page.add_freetext_annot(
        rect,
        text,
        fontsize=style.font_size,
        fontname=style.font or "Helv",
        text_color=_rgb(style.stroke),
        fill_color=_rgb(style.fill) if style.fill else None,
        opacity=max(0.0, min(1.0, style.opacity)),
        **callout_options,
        align=max(0, min(2, int(style.alignment))),
    )
    if boxed:
        # PyMuPDF 1.26 rejects border_color / border_width in the
        # non-rich-text constructor. Apply the same appearance afterward.
        annot.set_border(width=max(0.0, style.width))
        red, green, blue = _rgb(style.stroke)
        doc.xref_set_key(annot.xref, "C", f"[{red:g} {green:g} {blue:g}]")
    if not callout_points:
        for key in ("CL", "IT", "LE"):
            doc.xref_set_key(annot.xref, key, "null")
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
            info = dict(annot.info or {})
            border = dict(annot.border or {})
            colors = dict(annot.colors or {})
            results.append(
                {
                    "kind": kind,
                    "rect": rect,
                    "index": index,
                    "xref": int(annot.xref),
                    "text": str(info.get("content") or ""),
                    "stroke": colors.get("stroke"),
                    "fill": colors.get("fill"),
                    "opacity": float(annot.opacity),
                    "width": float(border.get("width") or 0),
                }
            )
    except Exception:
        pass  # the annotation list itself is stale
    return results


def remove_annotation(page: fitz.Page, xref: int) -> None:
    """Remove exactly the annotation identified by its stable PDF xref.

    An xref is not interchangeable with an annotation's position in the
    page's annotation list. In particular, falling back to a list index when
    a stale xref disappears can silently delete a different annotation.
    """
    with DOCUMENT_LOCK:
        try:
            annots = list(page.annots())
        except Exception:
            return  # stale annotation list after a page rebuild
        target = next((annot for annot in annots if int(annot.xref) == int(xref)), None)
        if target is not None:
            try:
                page.delete_annot(target)
            except Exception:
                pass  # the xref vanished mid-operation


def update_annotation(
    page: fitz.Page,
    xref: int,
    style: AnnotationStyle,
    *,
    text: str | None = None,
) -> bool:
    """Update an existing annotation by stable xref."""

    with DOCUMENT_LOCK:
        target = next(
            (
                annot
                for annot in list(page.annots() or [])
                if int(annot.xref) == int(xref)
            ),
            None,
        )
        if target is None:
            return False
        colors: dict[str, tuple[float, float, float]] = {"stroke": _rgb(style.stroke)}
        if style.fill:
            colors["fill"] = _rgb(style.fill)
        try:
            target.set_colors(**colors)
        except (RuntimeError, ValueError):
            pass
        try:
            target.set_border(width=max(0.0, style.width))
        except (RuntimeError, ValueError):
            pass
        target.set_opacity(max(0.0, min(1.0, style.opacity)))
        if text is not None:
            info = dict(target.info or {})
            info["content"] = text
            target.set_info(info)
        update_options: dict[str, object] = {}
        if "FreeText" in str(target.type[1]):
            update_options = {
                "fontsize": style.font_size,
                "fontname": style.font or "Helv",
                "text_color": _rgb(style.stroke),
                "fill_color": _rgb(style.fill) if style.fill else None,
                "align": max(0, min(2, int(style.alignment))),
            }
        target.update(**update_options)
        return True


def apply_annotation(doc: fitz.Document, op: AnnotationOp) -> None:
    """Apply one AnnotationOp to the live document (serialized against renders)."""
    with DOCUMENT_LOCK:
        style = op.style or AnnotationStyle(stroke=op.color, width=op.width)
        if op.kind in {"highlight", "underline", "strikeout", "squiggly"}:
            handler = {
                "highlight": add_highlight,
                "underline": add_underline,
                "strikeout": add_strikeout,
                "squiggly": add_squiggly,
            }[op.kind]
            handler(doc, op.page, list(op.rects), style.stroke)
        elif op.kind == "note":
            add_note(doc, op.page, op.points[0] if op.points else (0, 0), op.text)
        elif op.kind == "ink":
            add_ink(doc, op.page, op.points, style.stroke, style.width)
        elif op.kind == "rect":
            add_rect(doc, op.page, op.rects[0], style.stroke, style.width)
        elif op.kind == "line":
            add_line(
                doc, op.page, op.points[0], op.points[1], style.stroke, style.width
            )
        elif op.kind == "arrow":
            add_arrow(doc, op.page, op.points[0], op.points[1], style)
        elif op.kind in {"circle", "ellipse"}:
            add_circle(doc, op.page, op.rects[0], style.stroke, style.width)
        elif op.kind == "polygon":
            add_polygon(doc, op.page, op.points, style.stroke, style.width)
        elif op.kind.startswith("freetext_"):
            add_freetext(
                doc,
                op.page,
                op.rects[0],
                op.text,
                style,
                callout=op.points if op.kind == "freetext_callout" else (),
                boxed=op.kind != "freetext_typewriter",
            )
        elif op.kind == "stamp":
            if op.image_path:
                insert_image(doc, op.page, op.rects[0], op.image_path)
            else:
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
