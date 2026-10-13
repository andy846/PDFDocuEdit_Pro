"""Promote selected Normal Appearances without rebuilding the page tree.

PDF appearance placement is in native PDF coordinates. Page rotation and
CropBox are handled by the existing page transform, not applied a second time.
"""
from __future__ import annotations

import math
import re
import uuid

import fitz


class AppearanceError(ValueError):
    pass


def numbers(document, xref, key, count):
    kind, value = document.xref_get_key(xref, key)
    if kind == "null" and key == "Matrix":
        return [1, 0, 0, 1, 0, 0]
    if kind != "array":
        raise AppearanceError(f"Object {xref}: missing or invalid {key}.")
    tokens = value.strip("[] ").split()
    if len(tokens) != count or any(not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", item) for item in tokens):
        raise AppearanceError(f"Object {xref}: invalid {key} coordinates.")
    result = [float(item) for item in tokens]
    if not all(math.isfinite(item) for item in result):
        raise AppearanceError(f"Object {xref}: non-finite {key} coordinates.")
    return result


def normal_appearance(document, xref):
    kind, value = document.xref_get_key(xref, "AP/N")
    indirect_dictionary = kind == "xref" and not document.xref_is_stream(int(value.split()[0]))
    if kind == "dict" or indirect_dictionary:
        state_kind, state = document.xref_get_key(xref, "AS")
        if state_kind != "name":
            raise AppearanceError(f"Object {xref}: a checkbox/radio appearance state is required.")
        kind, value = (document.xref_get_key(int(value.split()[0]), state.lstrip("/")) if indirect_dictionary else
                       document.xref_get_key(xref, "AP/N/" + state.lstrip("/")))
    if kind != "xref":
        raise AppearanceError(f"Object {xref}: no supported Normal Appearance. Repair its appearance first.")
    appearance = int(value.split()[0])
    if not document.xref_is_stream(appearance):
        raise AppearanceError(f"Object {xref}: appearance is not a stream.")
    return appearance


def _copy_dictionary(document, kind, value):
    if kind == "xref":
        value = document.xref_object(int(value.split()[0]), compressed=False)
    elif kind != "dict":
        value = "<< >>"
    xref = document.get_new_xref()
    document.update_object(xref, value)
    return xref


def _resources(document, page):
    xref, visited = page.xref, set()
    while xref not in visited:
        visited.add(xref)
        kind, value = document.xref_get_key(xref, "Resources")
        if kind != "null":
            break
        parent_kind, parent = document.xref_get_key(xref, "Parent")
        if parent_kind != "xref":
            break
        xref = int(parent.split()[0])
    resource = _copy_dictionary(document, kind, value)
    # Clone the nested dictionary too: an inherited/shared XObject dictionary
    # must not be modified on another page.
    object_kind, object_value = document.xref_get_key(resource, "XObject")
    objects = _copy_dictionary(document, object_kind, object_value)
    document.xref_set_key(resource, "XObject", f"{objects} 0 R")
    document.xref_set_key(page.xref, "Resources", f"{resource} 0 R")
    return objects


def promote_appearance(document, page, xref):
    appearance = normal_appearance(document, xref)
    rectangle = fitz.Rect(numbers(document, xref, "Rect", 4))
    bbox = fitz.Rect(numbers(document, appearance, "BBox", 4))
    transformed = bbox * fitz.Matrix(*numbers(document, appearance, "Matrix", 6))
    if rectangle.is_empty or transformed.is_empty:
        raise AppearanceError(f"Object {xref}: empty appearance bounds.")
    sx, sy = rectangle.width / transformed.width, rectangle.height / transformed.height
    tx, ty = rectangle.x0 - transformed.x0 * sx, rectangle.y0 - transformed.y0 * sy
    name = "PDCEFlatten" + uuid.uuid4().hex
    objects = _resources(document, page)
    document.xref_set_key(objects, name, f"{appearance} 0 R")
    stream = document.get_new_xref()
    document.update_object(stream, "<< >>")
    # PDF numbers do not accept exponent notation (e.g. 1e-10). Tiny
    # placement offsets from Highlight/Underline appearances are common.
    def number(value):
        text = f"{value:.12f}".rstrip("0").rstrip(".")
        return "0" if text in ("", "-0") else text
    document.update_stream(stream, f"q {number(sx)} 0 0 {number(sy)} {number(tx)} {number(ty)} cm /{name} Do Q\n".encode("ascii"))
    contents = page.get_contents()
    # Existing content must not leak an unterminated graphics state into the
    # appearance. wrap_contents uses MuPDF's existing safe content wrapper.
    page.wrap_contents()
    contents = page.get_contents()
    document.xref_set_key(page.xref, "Contents", "[" + " ".join(f"{item} 0 R" for item in [*contents, stream]) + "]")


def flatten_page(document, index, *, annotations=True, widgets=False):
    page = document[index]
    annotations_to_flatten = [a.xref for a in page.annots() or []] if annotations else []
    widgets_to_flatten = [w.xref for w in page.widgets() or []] if widgets else []
    selected = []
    for xref in [*annotations_to_flatten, *widgets_to_flatten]:
        _, flags = document.xref_get_key(xref, "F")
        if flags.lstrip("-").isdigit() and int(flags) & (1 | 2 | 32):
            continue  # Invisible, Hidden or NoView: never reveal hidden content.
        _, subtype = document.xref_get_key(xref, "Subtype")
        if subtype == "/Redact":
            raise AppearanceError("Unapplied redaction marks cannot be flattened. Apply redactions first.")
        normal_appearance(document, xref)
        selected.append(xref)
    # Validate the entire selected page before promoting any appearance.
    for xref in selected:
        promote_appearance(document, page, xref)
        if xref in widgets_to_flatten:
            page.delete_widget(page.load_widget(xref))
        else:
            page.delete_annot(page.load_annot(xref))
        # No GUI page is shared with the worker. Deletion updates the loaded
        # annotation list; final QC reopens the saved PDF. reload_page can
        # assert in MuPDF 1.26 when another native handle retains this page.
    return len(selected)
