"""Pure PyMuPDF annotation and content-editing operations (no Qt imports)."""

from __future__ import annotations

import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from math import hypot, isfinite
from pathlib import Path

import fitz

from .pdf_engine import DOCUMENT_LOCK
from .system_fonts import is_pdf_base_font, resolve_system_font

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

SUPPORTED_ANNOTATION_KINDS = frozenset(
    {
        "highlight",
        "underline",
        "strikeout",
        "squiggly",
        "note",
        "ink",
        "rect",
        "line",
        "arrow",
        "circle",
        "ellipse",
        "polygon",
        "freetext_typewriter",
        "freetext_box",
        "freetext_callout",
        "redact",
        "stamp",
        "signature_image",
        "image",
    }
)


class AnnotationValidationError(ValueError):
    """An annotation request is malformed and must not reach PyMuPDF."""


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
            "signature_image": "Signature Image",
            "image": "Image",
        }
        return labels.get(self.kind, self.kind.title())


@lru_cache(maxsize=256)
def freetext_visual_metrics(
    font_name: str,
    font_size: float,
) -> tuple[float, float]:
    """Return the FreeText glyph midpoint offset and a safe line height.

    PyMuPDF's Base-14 FreeText appearance uses a baseline at 0.8 em, while
    our embedded system-font appearance starts at the text rectangle's top.
    Keeping this distinction here lets the canvas place either appearance by
    its visible glyph centre instead of by the annotation rectangle.
    """

    size = max(4.0, float(font_size))
    requested = str(font_name or "Helv")
    system_path = None if is_pdf_base_font(requested) else resolve_system_font(requested)
    base_font_name = {
        "helv": "helv",
        "cour": "cour",
        "times-roman": "tiro",
    }.get(requested.strip().casefold(), "helv")
    try:
        font = (
            fitz.Font(fontfile=str(system_path))
            if system_path is not None
            else fitz.Font(fontname=base_font_name)
        )
        ascender = float(font.ascender)
        descender = float(font.descender)
    except Exception:
        ascender, descender = 1.075, -0.299
        system_path = None
    line_height = max(size, (ascender - descender) * size)
    midpoint = (
        line_height / 2.0
        if system_path is not None
        else size * (0.8 - (ascender + descender) / 2.0)
    )
    return max(0.0, midpoint), max(size * 1.6, line_height)


def _quads(rects: Iterable[fitz.Rect]) -> list[fitz.Quad]:
    return [rect.quad for rect in rects]


def parse_annotation_color(color: str) -> tuple[float, float, float]:
    """Strictly parse a named palette color, #RRGGBB or #AARRGGBB."""
    value = str(color).strip()
    named = ANNOT_COLORS.get(value.casefold())
    if named is not None:
        return named
    if value.startswith("#") and len(value) in {7, 9}:
        rgb = value[-6:]
        try:
            return tuple(
                int(rgb[index : index + 2], 16) / 255.0 for index in (0, 2, 4)
            )
        except ValueError as exc:
            raise AnnotationValidationError(
                f"Invalid annotation color: {color!r}"
            ) from exc
    raise AnnotationValidationError(f"Invalid annotation color: {color!r}")


def _rgb(color: str) -> tuple[float, float, float]:
    return parse_annotation_color(color)


def validate_annotation_op(doc: fitz.Document, op: AnnotationOp) -> AnnotationOp:
    """Validate and normalize one request before an undo entry or PDF mutation."""

    with DOCUMENT_LOCK:
        kind = "signature_image" if op.kind == "signature" else str(op.kind)
        if kind not in SUPPORTED_ANNOTATION_KINDS:
            raise AnnotationValidationError(f"Unknown annotation kind: {op.kind}")
        if not 0 <= int(op.page) < doc.page_count:
            raise AnnotationValidationError("The annotation target page is invalid.")

        style = op.style or AnnotationStyle(stroke=op.color, width=op.width)
        if not isfinite(float(style.width)) or float(style.width) <= 0:
            raise AnnotationValidationError("Annotation width must be greater than zero.")
        if not isfinite(float(style.opacity)) or not 0 <= float(style.opacity) <= 1:
            raise AnnotationValidationError("Annotation opacity must be between 0 and 1.")
        parse_annotation_color(style.stroke)
        if style.fill:
            parse_annotation_color(style.fill)

        page_rect = doc.load_page(op.page).rect
        rects: list[fitz.Rect] = []
        for source in op.rects:
            rect = (fitz.Rect(source).normalize() & page_rect).normalize()
            if (
                not all(isfinite(value) for value in (rect.x0, rect.y0, rect.x1, rect.y1))
                or rect.is_empty
                or rect.width < 1
                or rect.height < 1
            ):
                raise AnnotationValidationError(
                    "Draw a larger annotation area inside the page."
                )
            rects.append(rect)

        points: list[tuple[float, float]] = []
        for source in op.points:
            if len(source) < 2:
                raise AnnotationValidationError("Annotation point is incomplete.")
            x, y = float(source[0]), float(source[1])
            if not isfinite(x) or not isfinite(y):
                raise AnnotationValidationError("Annotation point must be finite.")
            points.append((x, y))

        rect_kinds = {
            "highlight",
            "underline",
            "strikeout",
            "squiggly",
            "rect",
            "circle",
            "ellipse",
            "freetext_typewriter",
            "freetext_box",
            "freetext_callout",
            "redact",
            "stamp",
            "signature_image",
            "image",
        }
        if kind in rect_kinds and not rects:
            raise AnnotationValidationError(f"{op.description()} requires an area.")
        minimum_points = {
            "note": 1,
            "ink": 2,
            "line": 2,
            "arrow": 2,
            "polygon": 3,
        }
        required = minimum_points.get(kind, 0)
        if len(points) < required:
            raise AnnotationValidationError(
                f"{op.description()} requires at least {required} point"
                f"{'s' if required != 1 else ''}."
            )
        if kind in {"line", "arrow"} and len(points) != 2:
            raise AnnotationValidationError(f"{op.description()} requires two endpoints.")
        if kind == "freetext_callout" and len(points) != 3:
            raise AnnotationValidationError("Callout requires three leader-line points.")
        if kind.startswith("freetext_") and not op.text.strip():
            raise AnnotationValidationError("FreeText content cannot be empty.")
        if kind in {"signature_image", "image"} and not Path(op.image_path).is_file():
            raise AnnotationValidationError("Choose an existing image file.")
        if kind == "stamp" and op.image_path and not Path(op.image_path).is_file():
            raise AnnotationValidationError("The custom stamp image no longer exists.")

        return replace(
            op,
            kind=kind,
            rects=tuple(rects),
            points=tuple(points),
            style=style,
        )


def _page(doc: fitz.Document, page_num: int) -> fitz.Page:
    return doc.load_page(page_num)


_SYSTEM_FONT_KEY = "PDFdocuEditFont"
_TEXT_RECT_KEY = "PDFdocuEditTextRect"
_CALLOUT_KEY = "PDFdocuEditCallout"
_BOXED_KEY = "PDFdocuEditBoxed"


def _xref_string(doc: fitz.Document, xref: int, key: str) -> str:
    try:
        kind, value = doc.xref_get_key(xref, key)
    except (RuntimeError, ValueError):
        return ""
    return value if kind == "string" else ""


def _xref_numbers(doc: fitz.Document, xref: int, key: str) -> tuple[float, ...]:
    try:
        kind, value = doc.xref_get_key(xref, key)
    except (RuntimeError, ValueError):
        return ()
    if kind != "array":
        return ()
    try:
        return tuple(float(part) for part in value.strip("[] ").split())
    except ValueError:
        return ()


def _pdf_array(values: Iterable[float]) -> str:
    return "[" + " ".join(f"{float(value):.6g}" for value in values) + "]"


def _system_font_family(doc: fitz.Document, xref: int) -> str:
    return _xref_string(doc, xref, _SYSTEM_FONT_KEY)


def _appearance_xref(doc: fitz.Document, annot_xref: int) -> int | None:
    try:
        kind, value = doc.xref_get_key(annot_xref, "AP/N")
        if kind == "xref":
            return int(value.split()[0])
    except (IndexError, RuntimeError, TypeError, ValueError):
        pass
    return None


def _draw_open_arrow(
    page: fitz.Page,
    tip: fitz.Point,
    next_point: fitz.Point,
    color: tuple[float, float, float],
    width: float,
) -> None:
    dx, dy = next_point.x - tip.x, next_point.y - tip.y
    length = hypot(dx, dy)
    if length < 0.01:
        return
    ux, uy = dx / length, dy / length
    size = max(7.0, width * 4.0)
    spread = size * 0.45
    base_x, base_y = tip.x + ux * size, tip.y + uy * size
    perpendicular_x, perpendicular_y = -uy * spread, ux * spread
    page.draw_polyline(
        [
            fitz.Point(base_x + perpendicular_x, base_y + perpendicular_y),
            tip,
            fitz.Point(base_x - perpendicular_x, base_y - perpendicular_y),
        ],
        color=color,
        width=width,
        overlay=True,
    )


def _set_system_freetext_appearance(
    doc: fitz.Document,
    page_num: int,
    annot_xref: int,
    text_rect: fitz.Rect,
    text: str,
    style: AnnotationStyle,
    *,
    boxed: bool,
    callout: Sequence[tuple[float, float]] = (),
) -> bool:
    """Embed a system font and install a portable FreeText appearance stream."""

    font_path = resolve_system_font(style.font)
    appearance_xref = _appearance_xref(doc, annot_xref)
    if font_path is None or appearance_xref is None:
        return False

    target_page = doc.load_page(page_num)
    target = next(
        (
            annot
            for annot in list(target_page.annots() or [])
            if int(annot.xref) == int(annot_xref)
        ),
        None,
    )
    if target is None:
        return False
    appearance_rect = fitz.Rect(target.rect).normalize()
    width = max(1.0, appearance_rect.width)
    height = max(1.0, appearance_rect.height)
    local_text = fitz.Rect(
        text_rect.x0 - appearance_rect.x0,
        text_rect.y0 - appearance_rect.y0,
        text_rect.x1 - appearance_rect.x0,
        text_rect.y1 - appearance_rect.y0,
    ).normalize()

    temp_index = doc.page_count
    temp_page = doc.new_page(width=width, height=height)
    stroke = _rgb(style.stroke)
    if len(callout) == 3:
        local_points = [
            fitz.Point(x - appearance_rect.x0, y - appearance_rect.y0)
            for x, y in callout
        ]
        temp_page.draw_polyline(
            local_points,
            color=stroke,
            width=max(0.5, style.width),
            overlay=True,
        )
        _draw_open_arrow(
            temp_page,
            local_points[0],
            local_points[1],
            stroke,
            max(0.5, style.width),
        )
    if boxed:
        temp_page.draw_rect(
            local_text,
            color=stroke,
            fill=_rgb(style.fill) if style.fill else None,
            width=max(0.5, style.width),
            overlay=True,
        )

    inset = max(1.5, style.width + 1.0) if boxed else 0.0
    text_area = fitz.Rect(
        local_text.x0 + inset,
        local_text.y0 + inset,
        local_text.x1 - inset,
        local_text.y1 - inset,
    )
    if text_area.is_empty:
        text_area = local_text
    actual_size = max(4.0, float(style.font_size))
    inserted = False
    while actual_size >= 4.0:
        remaining = temp_page.insert_textbox(
            text_area,
            str(text),
            fontname="PdfDocuEditSystemFont",
            fontfile=str(font_path),
            fontsize=actual_size,
            color=stroke,
            align=max(0, min(2, int(style.alignment))),
            overlay=True,
        )
        if remaining >= 0:
            inserted = True
            break
        actual_size -= 1.0
    if not inserted:
        temp_page.insert_text(
            fitz.Point(text_area.x0, text_area.y0 + 4.0),
            str(text),
            fontname="PdfDocuEditSystemFont",
            fontfile=str(font_path),
            fontsize=4.0,
            color=stroke,
            overlay=True,
        )

    resources = doc.xref_get_key(temp_page.xref, "Resources")
    streams = [doc.xref_stream(xref) for xref in temp_page.get_contents()]
    stream = b"\n".join(value for value in streams if value)
    doc.delete_page(temp_index)

    if resources[0] not in {"xref", "dict"} or not stream:
        return False
    doc.xref_set_key(appearance_xref, "Resources", resources[1])
    doc.xref_set_key(appearance_xref, "BBox", _pdf_array((0, 0, width, height)))
    doc.xref_set_key(appearance_xref, "Matrix", "[1 0 0 1 0 0]")
    doc.update_stream(appearance_xref, stream)
    doc.xref_set_key(annot_xref, _SYSTEM_FONT_KEY, fitz.get_pdf_str(style.font))
    doc.xref_set_key(annot_xref, _TEXT_RECT_KEY, _pdf_array(text_rect))
    doc.xref_set_key(annot_xref, _BOXED_KEY, "true" if boxed else "false")
    doc.xref_set_key(
        annot_xref,
        _CALLOUT_KEY,
        _pdf_array(value for point in callout for value in point) if callout else "null",
    )
    return True


def add_highlight(
    doc: fitz.Document,
    page_num: int,
    rects: Sequence[fitz.Rect],
    color: str = DEFAULT_COLOR,
    opacity: float = 1.0,
) -> None:
    page = _page(doc, page_num)
    annot = page.add_highlight_annot(quads=_quads(rects))
    annot.set_colors(stroke=_rgb(color))
    annot.set_opacity(max(0.0, min(1.0, opacity)))
    annot.update()


def add_underline(
    doc: fitz.Document,
    page_num: int,
    rects: Sequence[fitz.Rect],
    color: str = DEFAULT_COLOR,
    opacity: float = 1.0,
) -> None:
    page = _page(doc, page_num)
    annot = page.add_underline_annot(quads=_quads(rects))
    annot.set_colors(stroke=_rgb(color))
    annot.set_opacity(max(0.0, min(1.0, opacity)))
    annot.update()


def add_strikeout(
    doc: fitz.Document,
    page_num: int,
    rects: Sequence[fitz.Rect],
    color: str = DEFAULT_COLOR,
    opacity: float = 1.0,
) -> None:
    page = _page(doc, page_num)
    annot = page.add_strikeout_annot(quads=_quads(rects))
    annot.set_colors(stroke=_rgb(color))
    annot.set_opacity(max(0.0, min(1.0, opacity)))
    annot.update()


def add_squiggly(
    doc: fitz.Document,
    page_num: int,
    rects: Sequence[fitz.Rect],
    color: str = DEFAULT_COLOR,
    opacity: float = 1.0,
) -> None:
    page = _page(doc, page_num)
    annot = page.add_squiggly_annot(quads=_quads(rects))
    annot.set_colors(stroke=_rgb(color))
    annot.set_opacity(max(0.0, min(1.0, opacity)))
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
    opacity: float = 1.0,
) -> None:
    page = _page(doc, page_num)
    annot = page.add_ink_annot([list(points)])
    annot.set_border(width=width)
    annot.set_colors(stroke=_rgb(color))
    annot.set_opacity(max(0.0, min(1.0, opacity)))
    annot.update()


def add_rect(
    doc: fitz.Document,
    page_num: int,
    rect: fitz.Rect,
    color: str = "red",
    width: float = 1.5,
    fill: str = "",
    opacity: float = 1.0,
) -> None:
    page = _page(doc, page_num)
    annot = page.add_rect_annot(rect)
    annot.set_border(width=width)
    colors: dict[str, tuple[float, float, float]] = {"stroke": _rgb(color)}
    if fill:
        colors["fill"] = _rgb(fill)
    annot.set_colors(**colors)
    annot.set_opacity(max(0.0, min(1.0, opacity)))
    annot.update()


def add_line(
    doc: fitz.Document,
    page_num: int,
    p1: tuple[float, float],
    p2: tuple[float, float],
    color: str = "red",
    width: float = 1.5,
    opacity: float = 1.0,
) -> None:
    page = _page(doc, page_num)
    annot = page.add_line_annot(fitz.Point(p1), fitz.Point(p2))
    annot.set_border(width=width)
    annot.set_colors(stroke=_rgb(color))
    annot.set_opacity(max(0.0, min(1.0, opacity)))
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
    fill: str = "",
    opacity: float = 1.0,
) -> None:
    page = _page(doc, page_num)
    annot = page.add_circle_annot(rect)
    annot.set_border(width=width)
    colors: dict[str, tuple[float, float, float]] = {"stroke": _rgb(color)}
    if fill:
        colors["fill"] = _rgb(fill)
    annot.set_colors(**colors)
    annot.set_opacity(max(0.0, min(1.0, opacity)))
    annot.update()


def add_polygon(
    doc: fitz.Document,
    page_num: int,
    points: Sequence[tuple[float, float]],
    color: str = "red",
    width: float = 1.5,
    fill: str = "",
    opacity: float = 1.0,
) -> None:
    page = _page(doc, page_num)
    annot = page.add_polygon_annot(list(points))
    annot.set_border(width=width)
    colors: dict[str, tuple[float, float, float]] = {"stroke": _rgb(color)}
    if fill:
        colors["fill"] = _rgb(fill)
    annot.set_colors(**colors)
    annot.set_opacity(max(0.0, min(1.0, opacity)))
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
    requested_font = style.font or "Helv"
    pdf_font = requested_font if is_pdf_base_font(requested_font) else "Helv"
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
        fontname=pdf_font,
        text_color=_rgb(style.stroke),
        fill_color=_rgb(style.fill) if style.fill else None,
        opacity=max(0.0, min(1.0, style.opacity)),
        **callout_options,
        align=max(0, min(2, int(style.alignment))),
    )
    if boxed:
        # PyMuPDF 1.26 rejects border_color / border_width in the
        # non-rich-text constructor. Set only the border width afterward,
        # then regenerate the appearance with text and background explicitly.
        # For FreeText, PDF /C is the background color -- overwriting it with
        # the text color makes the text disappear into an identical fill.
        annot.set_border(width=max(0.0, style.width))
    if not callout_points:
        for key in ("CL", "IT", "LE"):
            doc.xref_set_key(annot.xref, key, "null")
    annot.update(
        fontsize=style.font_size,
        fontname=pdf_font,
        text_color=_rgb(style.stroke),
        fill_color=_rgb(style.fill) if style.fill else None,
    )
    if not is_pdf_base_font(requested_font):
        _set_system_freetext_appearance(
            doc,
            page_num,
            int(annot.xref),
            fitz.Rect(rect),
            text,
            style,
            boxed=boxed,
            callout=tuple(callout),
        )


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
    """Add reviewable redaction marks without destroying page content."""
    page = _page(doc, page_num)
    for rect in rects:
        page.add_redact_annot(rect)


def apply_redaction_marks(
    doc: fitz.Document,
    pages: Iterable[int] | None = None,
    *,
    images: int = fitz.PDF_REDACT_IMAGE_PIXELS,
    graphics: int = fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
    text: int = fitz.PDF_REDACT_TEXT_REMOVE,
) -> int:
    """Permanently apply redaction marks on selected pages and return the count."""

    with DOCUMENT_LOCK:
        selected = (
            range(doc.page_count)
            if pages is None
            else dict.fromkeys(int(page) for page in pages)
        )
        applied = 0
        for page_num in selected:
            if not 0 <= page_num < doc.page_count:
                continue
            page = doc.load_page(page_num)
            redactions = [
                annot
                for annot in list(page.annots() or [])
                if "Redact" in str(annot.type[1])
            ]
            if not redactions:
                continue
            if page.apply_redactions(images=images, graphics=graphics, text=text):
                applied += len(redactions)
        return applied


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
            stroke = colors.get("stroke")
            fill = colors.get("fill")
            font = ""
            font_size = 0.0
            alignment = 0
            if kind == "FreeText":
                # PyMuPDF exposes FreeText /C as ``stroke`` even though /C is
                # rendered as its background. Text color lives in /DA.
                fill = stroke
                try:
                    default_appearance = page.parent.xref_get_key(
                        annot.xref, "DA"
                    )[1]
                    parts = default_appearance.split()
                    font_index = parts.index("Tf")
                    if font_index >= 2:
                        font = parts[font_index - 2].lstrip("/")
                        font_size = float(parts[font_index - 1])
                    color_index = parts.index("rg")
                    if color_index >= 3:
                        stroke = tuple(
                            float(value)
                            for value in parts[color_index - 3 : color_index]
                        )
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass
                font = _system_font_family(page.parent, annot.xref) or font
                try:
                    alignment = int(page.parent.xref_get_key(annot.xref, "Q")[1])
                except (RuntimeError, TypeError, ValueError):
                    alignment = 0
            try:
                vertices = [
                    (float(point[0]), float(point[1]))
                    for point in list(annot.vertices or [])
                ]
            except (RuntimeError, TypeError, ValueError):
                vertices = []
            try:
                line_ends = tuple(int(value) for value in annot.line_ends)
            except (RuntimeError, TypeError, ValueError):
                line_ends = ()
            results.append(
                {
                    "kind": kind,
                    "rect": rect,
                    "index": index,
                    "xref": int(annot.xref),
                    "text": str(info.get("content") or ""),
                    "title": str(info.get("title") or ""),
                    "subject": str(info.get("subject") or ""),
                    "creation_date": str(info.get("creationDate") or ""),
                    "modified_date": str(info.get("modDate") or ""),
                    "stroke": stroke,
                    "fill": fill,
                    "opacity": float(annot.opacity),
                    "width": float(border.get("width") or 0),
                    "font": font,
                    "font_size": font_size,
                    "alignment": alignment,
                    "vertices": vertices,
                    "line_ends": line_ends,
                }
            )
    except Exception:
        pass  # the annotation list itself is stale
    return results


def list_document_annotations(doc: fitz.Document) -> list[dict]:
    """Return stable annotation records for every page in document order."""

    with DOCUMENT_LOCK:
        records: list[dict] = []
        for page_num in range(doc.page_count):
            page = doc.load_page(page_num)
            for entry in list_annotations(page):
                entry["page"] = page_num
                records.append(entry)
        return records


def remove_annotation(page: fitz.Page, xref: int) -> bool:
    """Remove exactly the annotation identified by its stable PDF xref.

    An xref is not interchangeable with an annotation's position in the
    page's annotation list. In particular, falling back to a list index when
    a stale xref disappears can silently delete a different annotation.
    """
    with DOCUMENT_LOCK:
        try:
            annots = list(page.annots())
        except Exception:
            return False  # stale annotation list after a page rebuild
        target = next((annot for annot in annots if int(annot.xref) == int(xref)), None)
        if target is not None:
            try:
                page.delete_annot(target)
                return True
            except Exception:
                return False  # the xref vanished mid-operation
        return False


def update_annotation_geometry(
    page: fitz.Page,
    xref: int,
    *,
    rect: fitz.Rect | None = None,
    points: Sequence[tuple[float, float]] = (),
) -> int | None:
    """Move/resize an annotation and return its stable (possibly new) xref."""

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
            return None
        kind = str(target.type[1])
        if kind == "Line" and len(points) == 2:
            border = dict(target.border or {})
            colors = dict(target.colors or {})
            stroke = colors.get("stroke") or (1.0, 0.0, 0.0)
            color = "#" + "".join(
                f"{max(0, min(255, round(float(channel) * 255))):02x}"
                for channel in stroke[:3]
            )
            new_annot = page.add_line_annot(
                fitz.Point(points[0]), fitz.Point(points[1])
            )
            new_annot.set_border(width=max(0.5, float(border.get("width") or 1.5)))
            new_annot.set_colors(stroke=_rgb(color))
            try:
                new_annot.set_line_ends(*target.line_ends)
            except (RuntimeError, TypeError, ValueError):
                pass
            new_annot.set_opacity(max(0.0, min(1.0, float(target.opacity))))
            try:
                new_annot.set_info(**dict(target.info or {}))
            except (RuntimeError, TypeError, ValueError):
                pass
            new_annot.update()
            new_xref = int(new_annot.xref)
            page.delete_annot(target)
            return new_xref
        if rect is None:
            return None
        clipped = (fitz.Rect(rect).normalize() & page.rect).normalize()
        if clipped.is_empty or clipped.width < 1 or clipped.height < 1:
            return None
        old_rect = fitz.Rect(target.rect).normalize()
        system_font = _system_font_family(page.parent, target.xref)
        stored_text_rect = _freetext_text_rect(page.parent, target) if system_font else None
        stored_callout = _freetext_callout(page.parent, target) if system_font else ()
        target.set_rect(clipped)
        if system_font and not old_rect.is_empty:
            scale_x = clipped.width / old_rect.width
            scale_y = clipped.height / old_rect.height

            def transform_point(x: float, y: float) -> tuple[float, float]:
                return (
                    clipped.x0 + (x - old_rect.x0) * scale_x,
                    clipped.y0 + (y - old_rect.y0) * scale_y,
                )

            if stored_text_rect is not None:
                top_left = transform_point(stored_text_rect.x0, stored_text_rect.y0)
                bottom_right = transform_point(stored_text_rect.x1, stored_text_rect.y1)
                page.parent.xref_set_key(
                    target.xref,
                    _TEXT_RECT_KEY,
                    _pdf_array((*top_left, *bottom_right)),
                )
            if stored_callout:
                transformed = [transform_point(x, y) for x, y in stored_callout]
                page.parent.xref_set_key(
                    target.xref,
                    _CALLOUT_KEY,
                    _pdf_array(value for point in transformed for value in point),
                )
            return int(target.xref)
        target.update()
        return int(target.xref)


def _color_hex(value: Sequence[float] | None, default: str) -> str:
    if not value or len(value) < 3:
        return default
    return "#" + "".join(
        f"{max(0, min(255, round(float(channel) * 255))):02x}"
        for channel in value[:3]
    )


def _freetext_text_rect(doc: fitz.Document, target: fitz.Annot) -> fitz.Rect:
    stored = _xref_numbers(doc, target.xref, _TEXT_RECT_KEY)
    if len(stored) == 4:
        return fitz.Rect(stored)
    rect = fitz.Rect(target.rect)
    inset = _xref_numbers(doc, target.xref, "RD")
    if len(inset) == 4:
        candidate = fitz.Rect(
            rect.x0 + inset[0],
            rect.y0 + inset[1],
            rect.x1 - inset[2],
            rect.y1 - inset[3],
        )
        if not candidate.is_empty:
            return candidate
    return rect


def _freetext_callout(doc: fitz.Document, target: fitz.Annot) -> tuple[tuple[float, float], ...]:
    stored = _xref_numbers(doc, target.xref, _CALLOUT_KEY)
    if len(stored) == 6:
        return tuple((stored[index], stored[index + 1]) for index in range(0, 6, 2))
    try:
        vertices = list(target.vertices or [])
    except (RuntimeError, TypeError, ValueError):
        vertices = []
    if len(vertices) == 3:
        return tuple((float(point[0]), float(point[1])) for point in vertices)
    return ()


def _freetext_style(doc: fitz.Document, target: fitz.Annot) -> AnnotationStyle:
    colors = dict(target.colors or {})
    background = colors.get("stroke")
    stroke: Sequence[float] | None = None
    font = _system_font_family(doc, target.xref) or "Helv"
    font_size = 11.0
    try:
        parts = doc.xref_get_key(target.xref, "DA")[1].split()
        font_index = parts.index("Tf")
        font_size = float(parts[font_index - 1])
        color_index = parts.index("rg")
        stroke = tuple(float(value) for value in parts[color_index - 3 : color_index])
    except (IndexError, RuntimeError, TypeError, ValueError):
        pass
    try:
        alignment = int(doc.xref_get_key(target.xref, "Q")[1])
    except (RuntimeError, TypeError, ValueError):
        alignment = 0
    return AnnotationStyle(
        stroke=_color_hex(stroke, "#000000"),
        fill=_color_hex(background, "") if background else "",
        opacity=max(0.0, min(1.0, float(target.opacity))),
        width=max(0.0, float(dict(target.border or {}).get("width") or 0.0)),
        font=font,
        font_size=font_size,
        alignment=alignment,
    )


def update_annotation_text(page: fitz.Page, xref: int, text: str) -> bool:
    """Update note / FreeText content by stable xref."""

    with DOCUMENT_LOCK:
        target = next(
            (
                annot
                for annot in list(page.annots() or [])
                if int(annot.xref) == int(xref)
            ),
            None,
        )
        if target is None or str(target.type[1]) not in {"Text", "FreeText"}:
            return False
        target.set_info(content=str(text))
        system_font = _system_font_family(page.parent, target.xref)
        if str(target.type[1]) == "FreeText" and system_font:
            style = _freetext_style(page.parent, target)
            text_rect = _freetext_text_rect(page.parent, target)
            callout = _freetext_callout(page.parent, target)
            boxed = page.parent.xref_get_key(target.xref, _BOXED_KEY)[1] == "true"
            return _set_system_freetext_appearance(
                page.parent,
                page.number,
                int(target.xref),
                text_rect,
                str(text),
                style,
                boxed=boxed,
                callout=callout,
            )
        target.update()
        return True


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
        is_freetext = "FreeText" in str(target.type[1])
        page_num = page.number
        target_xref = int(target.xref)
        text_rect = _freetext_text_rect(page.parent, target) if is_freetext else None
        callout = _freetext_callout(page.parent, target) if is_freetext else ()
        boxed = (
            page.parent.xref_get_key(target.xref, _BOXED_KEY)[1] == "true"
            or max(0.0, float(dict(target.border or {}).get("width") or 0.0)) > 0
        ) if is_freetext else False
        if not is_freetext:
            colors: dict[str, tuple[float, float, float]] = {
                "stroke": _rgb(style.stroke)
            }
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
        if is_freetext:
            page.parent.xref_set_key(
                target.xref, "Q", str(max(0, min(2, int(style.alignment))))
            )
            update_options = {
                "fontsize": style.font_size,
                "fontname": style.font if is_pdf_base_font(style.font) else "Helv",
                "text_color": _rgb(style.stroke),
                "fill_color": _rgb(style.fill) if style.fill else None,
            }
        target.update(**update_options)
        if is_freetext and not is_pdf_base_font(style.font):
            content = text if text is not None else str(dict(target.info or {}).get("content") or "")
            return _set_system_freetext_appearance(
                page.parent,
                page_num,
                target_xref,
                text_rect or fitz.Rect(target.rect),
                content,
                style,
                boxed=boxed,
                callout=callout,
            )
        if is_freetext:
            for key in (_SYSTEM_FONT_KEY, _TEXT_RECT_KEY, _CALLOUT_KEY, _BOXED_KEY):
                page.parent.xref_set_key(target_xref, key, "null")
        return True


def apply_annotation(doc: fitz.Document, op: AnnotationOp) -> None:
    """Apply one AnnotationOp to the live document (serialized against renders)."""
    with DOCUMENT_LOCK:
        op = validate_annotation_op(doc, op)
        style = op.style or AnnotationStyle(stroke=op.color, width=op.width)
        if op.kind in {"highlight", "underline", "strikeout", "squiggly"}:
            handler = {
                "highlight": add_highlight,
                "underline": add_underline,
                "strikeout": add_strikeout,
                "squiggly": add_squiggly,
            }[op.kind]
            handler(doc, op.page, list(op.rects), style.stroke, style.opacity)
        elif op.kind == "note":
            add_note(doc, op.page, op.points[0] if op.points else (0, 0), op.text)
        elif op.kind == "ink":
            add_ink(
                doc, op.page, op.points, style.stroke, style.width, style.opacity
            )
        elif op.kind == "rect":
            add_rect(
                doc,
                op.page,
                op.rects[0],
                style.stroke,
                style.width,
                style.fill,
                style.opacity,
            )
        elif op.kind == "line":
            add_line(
                doc,
                op.page,
                op.points[0],
                op.points[1],
                style.stroke,
                style.width,
                style.opacity,
            )
        elif op.kind == "arrow":
            add_arrow(doc, op.page, op.points[0], op.points[1], style)
        elif op.kind in {"circle", "ellipse"}:
            add_circle(
                doc,
                op.page,
                op.rects[0],
                style.stroke,
                style.width,
                style.fill,
                style.opacity,
            )
        elif op.kind == "polygon":
            add_polygon(
                doc,
                op.page,
                op.points,
                style.stroke,
                style.width,
                style.fill,
                style.opacity,
            )
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
        elif op.kind in {"signature_image", "image"}:
            insert_image(doc, op.page, op.rects[0], op.image_path)
        else:
            raise ValueError(f"Unknown annotation kind: {op.kind}")


# --- watermarks ----------------------------------------------------------
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
    value = str(text).strip()
    if not value:
        raise ValueError("Watermark text cannot be empty.")
    size = max(4.0, float(fontsize))
    alpha = max(0.0, min(1.0, float(opacity)))
    with DOCUMENT_LOCK:
        for page_num in pages:
            if not 0 <= page_num < doc.page_count:
                continue
            page = doc.load_page(page_num)
            centre = page.rect.tl + (page.rect.br - page.rect.tl) * 0.5
            max_width = max(20.0, page.rect.width * 0.82)
            text_width = fitz.get_text_length(value, fontname="helv", fontsize=size)
            if text_width > max_width:
                size *= max_width / text_width
                text_width = max_width
            baseline = fitz.Point(
                centre.x - text_width / 2,
                centre.y + size * 0.35,
            )
            page.insert_text(
                baseline,
                value,
                fontname="helv",
                fontsize=size,
                color=color,
                fill_opacity=alpha,
                overlay=True,
                morph=(centre, fitz.Matrix(float(rotation))),
            )


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
