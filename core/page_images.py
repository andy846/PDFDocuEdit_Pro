"""Editable Add Image placements, stored as ordinary PDF page content.

Each placement owns a small content stream. Moving it changes that stream,
never the shared image XObject or unrelated page content. Image signatures use
the same placement service; they do not create cryptographic signatures.
"""

from __future__ import annotations

import re
from math import isfinite
from pathlib import Path

import fitz

from .pdf_engine import DOCUMENT_LOCK

_RECT = "PDFdocuEditImageRect"
_ASPECT = "PDFdocuEditImageAspect"
_ORIGIN = "PDFdocuEditImageOrigin"
_KIND = "PDFdocuEditImageKind"
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
    return {"kind": kind, "xref": xref, "rect": rect,
            "keep_aspect": aspect, "text": "", "subject": "Added image",
            "opacity": 1.0, "width": 0.0}


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
                   *, signature: bool = False) -> int:
    with DOCUMENT_LOCK:
        # PyMuPDF's insertion transform on rotated, cropped pages can use a
        # different CropBox origin. Insert in native page space then restore
        # the display rotation under the same document lock / transaction.
        rotation = page.rotation
        try:
            if rotation:
                page.set_rotation(0)
            # External PDFs need not enclose their original graphics state in
            # q/Q. insert_image wraps those streams automatically, creating
            # extra streams which are not the image. Capture our baseline
            # after wrapping so only the placement is identified and tagged.
            page.wrap_contents()
            before = set(page.get_contents())
            image_xref = page.insert_image(rect, filename=str(path), overlay=True)
        finally:
            if rotation:
                page.set_rotation(rotation)
        created = [xref for xref in page.get_contents() if xref not in before]
        if len(created) != 1:
            raise PageImageError("Unable to identify the new image placement.")
        xref = created[0]
        if _MATRIX.fullmatch(page.parent.xref_stream(xref)) is None:
            raise PageImageError("The image placement has no editable transform.")
        # insert_image preserves proportions and centres within the drawn box.
        width = float(page.parent.xref_get_key(image_xref, "Width")[1])
        height = float(page.parent.xref_get_key(image_xref, "Height")[1])
        scale = min(rect.width / width, rect.height / height)
        fitted = fitz.Rect(0, 0, width * scale, height * scale)
        fitted += (rect.x0 + (rect.width - fitted.width) / 2,
                   rect.y0 + (rect.height - fitted.height) / 2,
                   rect.x0 + (rect.width - fitted.width) / 2,
                   rect.y0 + (rect.height - fitted.height) / 2)
        _write_rect(page, xref, fitted)
        page.parent.xref_set_key(xref, _ASPECT, "true")
        page.parent.xref_set_key(xref, _KIND, "/Signature" if signature else "/Image")
        return xref


def _replace_content(page: fitz.Page, old: int, new: int | None) -> None:
    contents = [new if ref == old else ref for ref in page.get_contents()]
    value = "[" + " ".join(f"{ref} 0 R" for ref in contents if ref is not None) + "]"
    page.parent.xref_set_key(page.xref, "Contents", value)


def _image_transform(stream: bytes):
    match = _MATRIX.fullmatch(stream)
    if match is None:
        raise PageImageError("This image placement was changed by another PDF tool; editing it is blocked to protect page content.")
    values = tuple(float(part) for part in match[1].split())
    a, b, c, d, _e, _f = values
    if not all(isfinite(value) for value in values) or b != 0 or c != 0 or a <= 0 or d <= 0:
        raise PageImageError("This image transform is no longer supported for editing.")
    return match, values


def update_page_image(page: fitz.Page, xref: int, rect: fitz.Rect,
                      *, keep_aspect: bool | None = None) -> int | None:
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
        match, (a, b, c, d, e, f) = _image_transform(stream)
        old = entry["rect"]
        # Retain insert_image's native CropBox translation, including rotated
        # pages. Only the placement's scale and translation are changed.
        values = (a * rect.width / old.width, b, c,
                  d * rect.height / old.height,
                  e + rect.x0 - old.x0, f - (rect.y1 - old.y1))
        replacement = " ".join(f"{v:.9g}" for v in values).encode("ascii")
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
        return new_xref


def remove_page_image(page: fitz.Page, xref: int) -> bool:
    with DOCUMENT_LOCK:
        if _placement(page, xref) is None:
            return False
        # An external optimiser may have merged this stream with other page
        # content. Never remove the whole stream unless it is still our image.
        _image_transform(page.parent.xref_stream(xref))
        _replace_content(page, xref, None)
        return True
