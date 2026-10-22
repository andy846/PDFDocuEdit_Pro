"""Editable Add Image placements, stored as ordinary PDF page content.

Each placement owns a small content stream. Moving it changes that stream,
never the shared image XObject or unrelated page content. Image signatures use
the same placement service; they do not create cryptographic signatures.
"""

from __future__ import annotations

import hashlib
import re
from math import atan2, cos, degrees, hypot, isfinite, radians, sin
from pathlib import Path

from core.pdf_backend import fitz

from .pdf_engine import DOCUMENT_LOCK

_RECT = "PDFdocuEditImageRect"
_ASPECT = "PDFdocuEditImageAspect"
_ORIGIN = "PDFdocuEditImageOrigin"
_KIND = "PDFdocuEditImageKind"
_TRANSFORM_HASH = "PDFdocuEditImageTransformHash"
IMAGE_KINDS = frozenset({"Image", "Signature Image"})
_NUMBER = rb"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_MATRIX = re.compile(rb"\s*q\s+(" + rb"\s+".join([_NUMBER] * 6)
                     + rb")\s+cm\s+/[^\s/()[\]<>%]+\s+Do\s+Q\s*")


class PageImageError(ValueError):
    """A safe, user-readable placement validation error."""


def _placement(page: fitz.Page, xref: int, contents: set[int] | None = None) -> dict | None:
    # Membership matters: a stale selection must not edit another page's stream.
    if xref not in (contents if contents is not None else page.get_contents()):
        return None
    kind, value = page.parent.xref_get_key(xref, _RECT)
    if kind != "array":
        return None
    try:
        values = [float(part) for part in value.strip("[] ").split()]
        if len(values) != 4 or not all(isfinite(part) for part in values):
            return None
        rect = fitz.Rect(values)
        if rect.is_empty or rect.is_infinite:
            return None
        origin_kind, origin = page.parent.xref_get_key(xref, _ORIGIN)
        if origin_kind == "array":
            old_x, old_y = (float(value) for value in origin.strip("[] ").split())
            if not isfinite(old_x) or not isfinite(old_y):
                return None
            dx, dy = old_x - page.cropbox.x0, old_y - page.cropbox.y0
            rect += (dx, dy, dx, dy)
    except (ValueError, TypeError):
        return None
    aspect = page.parent.xref_get_key(xref, _ASPECT)[1] != "false"
    kind = "Signature Image" if page.parent.xref_get_key(xref, _KIND)[1] == "/Signature" else "Image"
    match = _MATRIX.fullmatch(page.parent.xref_stream(xref))
    angle = 0.
    geometry = {}
    if match:
        values = tuple(map(float, match[1].split()))
        a, b, *_ = values
        angle = (degrees(atan2(b, a)) - page.rotation + 180) % 360 - 180
        native = _native_matrix(page)
        matrix = fitz.Matrix(*values)
        quad = [fitz.Point(x, y) * matrix * native for x, y in ((0, 1), (1, 1), (0, 0), (1, 0))]
        geometry = {"image_quad": [(p.x, p.y) for p in quad],
                    "image_size": (hypot(quad[1].x - quad[0].x, quad[1].y - quad[0].y),
                                   hypot(quad[2].x - quad[0].x, quad[2].y - quad[0].y))}
    return {"kind": kind, "xref": xref, "rect": rect, "rotation": angle,
            "keep_aspect": aspect, "text": "", "subject": "Added image",
            "opacity": 1.0, "width": 0.0, **geometry}


def list_page_images(page: fitz.Page) -> list[dict]:
    with DOCUMENT_LOCK:
        contents = page.get_contents()
        membership = set(contents)
        return [entry for xref in contents
                if (entry := _placement(page, xref, membership)) is not None]


def _write_rect(page: fitz.Page, xref: int, rect: fitz.Rect) -> None:
    page.parent.xref_set_key(xref, _RECT,
                     "[" + " ".join(f"{v:.9g}" for v in rect) + "]")
    page.parent.xref_set_key(xref, _ORIGIN, f"[{page.cropbox.x0:.9g} {page.cropbox.y0:.9g}]")


def add_page_image(page: fitz.Page, rect: fitz.Rect, path: str | Path,
                   *, signature: bool = False, rotation: int = 0,
                   angle: float = 0, keep_aspect: bool = True) -> int:
    with DOCUMENT_LOCK:
        # PyMuPDF's insertion transform on rotated, cropped pages can use a
        # different CropBox origin. Insert in native page space then restore
        # the display rotation under the same document lock / transaction.
        page_rotation = page.rotation
        try:
            if page_rotation:
                page.set_rotation(0)
            # External PDFs need not enclose their original graphics state in
            # q/Q. insert_image wraps those streams automatically, creating
            # extra streams which are not the image. Capture our baseline
            # after wrapping so only the placement is identified and tagged.
            page.wrap_contents()
            before = set(page.get_contents())
            image_xref = page.insert_image(rect, filename=str(path), overlay=True, rotate=rotation,
                                          keep_proportion=keep_aspect)
        finally:
            if page_rotation:
                page.set_rotation(page_rotation)
        created = [xref for xref in page.get_contents() if xref not in before]
        if len(created) != 1:
            raise PageImageError("Unable to identify the new image placement.")
        xref = created[0]
        if _MATRIX.fullmatch(page.parent.xref_stream(xref)) is None:
            raise PageImageError("The image placement has no editable transform.")
        # insert_image preserves proportions and centres within the drawn box.
        width = float(page.parent.xref_get_key(image_xref, "Width")[1])
        height = float(page.parent.xref_get_key(image_xref, "Height")[1])
        if rotation % 180:
            width, height = height, width
        scale = min(rect.width / width, rect.height / height)
        fitted = fitz.Rect(0, 0, width * scale, height * scale)
        fitted += (rect.x0 + (rect.width - fitted.width) / 2,
                   rect.y0 + (rect.height - fitted.height) / 2,
                   rect.x0 + (rect.width - fitted.width) / 2,
                   rect.y0 + (rect.height - fitted.height) / 2)
        _write_rect(page, xref, fitted if keep_aspect else rect)
        page.parent.xref_set_key(xref, _ASPECT, "true" if keep_aspect else "false")
        page.parent.xref_set_key(xref, _KIND, "/Signature" if signature else "/Image")
        _write_transform_hash(page, xref)
        if angle:
            xref = update_page_image(page, xref, fitted if keep_aspect else rect, rotation=angle)
        return xref


def _replace_content(page: fitz.Page, old: int, new: int | None) -> None:
    contents = [new if ref == old else ref for ref in page.get_contents()]
    value = "[" + " ".join(f"{ref} 0 R" for ref in contents if ref is not None) + "]"
    page.parent.xref_set_key(page.xref, "Contents", value)


def _write_transform_hash(page, xref):
    digest = hashlib.sha256(page.parent.xref_stream(xref)).hexdigest()
    page.parent.xref_set_key(xref, _TRANSFORM_HASH, fitz.get_pdf_str(digest))


def _image_transform(stream: bytes, *, trusted_affine=False):
    match = _MATRIX.fullmatch(stream)
    if match is None:
        raise PageImageError("This image placement was changed by another PDF tool; editing it is blocked to protect page content.")
    values = tuple(float(part) for part in match[1].split())
    a, b, c, d, _e, _f = values
    orthogonal = (b == c == 0 and a * d > 0) or (a == d == 0 and b * c < 0)
    if (not all(isfinite(value) for value in values) or a * d - b * c <= 0
            or (not orthogonal and not trusted_affine)):
        raise PageImageError("This image transform is no longer supported for editing.")
    return match, values


def _native_matrix(page):
    rotation = page.rotation
    try:
        if rotation:
            page.set_rotation(0)
        return page.transformation_matrix
    finally:
        if rotation:
            page.set_rotation(rotation)


def _placement_delta(page: fitz.Page, old: fitz.Rect, rect: fitz.Rect) -> fitz.Matrix:
    """Map old native geometry to new geometry in the PDF content coordinate system."""
    sx, sy = rect.width / old.width, rect.height / old.height
    delta = fitz.Matrix(sx, 0, 0, sy, rect.x0 - sx * old.x0, rect.y0 - sy * old.y0)
    native = _native_matrix(page)
    return native * delta * ~native


def update_page_image(page: fitz.Page, xref: int, rect: fitz.Rect,
                      *, keep_aspect: bool | None = None,
                      rotation: float | None = None,
                      image_size: tuple[float, float] | None = None) -> int | None:
    with DOCUMENT_LOCK:
        entry = _placement(page, xref)
        if entry is None:
            return None
        rect = fitz.Rect(rect)
        bounds = page.rect * page.derotation_matrix
        if (not all(isfinite(v) for v in rect) or rect.width < 1 or rect.height < 1
                or not bounds.contains(rect)):
            raise PageImageError("Keep the image inside the page, with width and height at least 1 pt.")
        stream = page.parent.xref_stream(xref)
        hash_kind, digest = page.parent.xref_get_key(xref, _TRANSFORM_HASH)
        if hash_kind == "string" and hashlib.sha256(stream).hexdigest() != digest:
            raise PageImageError("This image placement was changed; editing is blocked to protect page content.")
        match, (a, b, c, d, e, f) = _image_transform(stream, trusted_affine=hash_kind == "string")
        old = entry["rect"]
        # Scale/translate the entire CTM, including its rotation-dependent
        # origin. Merely changing e/f by the rectangle delta moves inverted
        # or quarter-turned images to the wrong edge when they are resized.
        if rotation is not None and (not isfinite(rotation) or abs(rotation) > 360):
            raise PageImageError("Choose a finite angle between -360 and 360 degrees.")
        if image_size is not None or rotation is not None:
            native = _native_matrix(page)
            current = degrees(atan2(b, a))
            angle = current if rotation is None else rotation + page.rotation
            width, height = entry["image_size"] if image_size is None else image_size
            if not all(isfinite(v) and v >= 1 for v in (width, height)):
                raise PageImageError("Image width and height must be finite and at least 1 pt.")
            # Resize along the image's own axes. Scaling its axis-aligned
            # bounding rectangle would shear a slanted image and change angle.
            units = hypot(native.a, native.b)
            width, height = width / units, height / units
            ca, sa = cos(radians(angle)), sin(radians(angle))
            values = fitz.Matrix(width * ca, width * sa, -height * sa, height * ca, 0, 0)
            relative = fitz.Rect(0, 0, 1, 1) * values * native
            if abs((angle - current + 180) % 360 - 180) < .00001:
                centre = fitz.Point(rect.x0 + relative.width / 2, rect.y0 + relative.height / 2)
            else:
                # Rotating keeps the centre; an explicit X/Y change translates
                # that centre independently. Pure size edits retain X/Y bounds.
                centre = (old.tl + old.br) / 2 + (rect.tl - old.tl)
            centre *= ~native
            values.e = centre.x - (values.a + values.c) / 2
            values.f = centre.y - (values.b + values.d) / 2
            corners = [fitz.Point(x, y) * values * native for x, y in ((0, 0), (1, 0), (0, 1), (1, 1))]
            rect = fitz.Rect(min(p.x for p in corners), min(p.y for p in corners),
                             max(p.x for p in corners), max(p.y for p in corners))
            if not (bounds + (-.01, -.01, .01, .01)).contains(rect):
                raise PageImageError("The rotated image extends outside the page. Move it inward or reduce its size.")
        else:
            sx, sy = rect.width / old.width, rect.height / old.height
            if abs(sx - sy) > .00001 and abs(a * b) > .00001:
                raise PageImageError("Use image width and height to resize a rotated image without changing its angle.")
            values = fitz.Matrix(a, b, c, d, e, f) * _placement_delta(page, old, rect)
        # PDF numbers do not support scientific notation, including near-zero
        # sine/cosine values produced by repeated quarter-turn editing.
        replacement = " ".join(f"{v:.9f}" for v in values).encode("ascii")
        # PDF page duplication can share content streams. Copy on write keeps
        # editing this placement from changing a duplicate or another page.
        new_xref = page.parent.get_new_xref()
        page.parent.update_object(new_xref, page.parent.xref_object(xref))
        page.parent.update_stream(new_xref, stream[:match.start(1)] + replacement
                                  + stream[match.end(1):])
        _write_rect(page, new_xref, rect)
        if keep_aspect is not None:
            page.parent.xref_set_key(new_xref, _ASPECT, "true" if keep_aspect else "false")
        _replace_content(page, xref, new_xref)
        _write_transform_hash(page, new_xref)
        return new_xref


def remove_page_image(page: fitz.Page, xref: int) -> bool:
    with DOCUMENT_LOCK:
        if _placement(page, xref) is None:
            return False
        # An external optimiser may have merged this stream with other page
        # content. Never remove the whole stream unless it is still our image.
        stream = page.parent.xref_stream(xref)
        kind, digest = page.parent.xref_get_key(xref, _TRANSFORM_HASH)
        if kind == "string" and hashlib.sha256(stream).hexdigest() != digest:
            raise PageImageError("This image placement was changed; removal is blocked to protect page content.")
        _image_transform(stream, trusted_affine=kind == "string")
        _replace_content(page, xref, None)
        return True
