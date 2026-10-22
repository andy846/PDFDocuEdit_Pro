"""Rotate native stamp appearances without rasterizing or regenerating them."""
from math import atan2, degrees, isfinite

from core.pdf_backend import fitz


def _appearance(page, annot):
    kind, value = page.parent.xref_get_key(annot.xref, "AP")
    kind, value = (page.parent.xref_get_key(int(value.split()[0]), "N") if kind == "xref"
                   else page.parent.xref_get_key(annot.xref, "AP/N"))
    if kind != "xref":
        raise ValueError("This stamp has no editable appearance.")
    xref = int(value.split()[0])
    def numbers(key, default):
        kind, value = page.parent.xref_get_key(xref, key)
        return list(map(float, value.strip("[] ").split())) if kind == "array" else default
    matrix = numbers("Matrix", [1, 0, 0, 1, 0, 0])
    box = numbers("BBox", [])
    if len(matrix) != 6 or len(box) != 4 or not all(isfinite(v) for v in (*matrix, *box)):
        raise ValueError("The stamp appearance geometry is invalid.")
    return xref, fitz.Matrix(*matrix), fitz.Rect(box)


def stamp_rotation(page, annot):
    try:
        _, matrix, _ = _appearance(page, annot)
    except (ValueError, RuntimeError):
        return None
    return (degrees(atan2(matrix.b, matrix.a)) - page.rotation + 180) % 360 - 180


def update_stamp_geometry(page, annot, rect, rotation=None):
    doc = page.parent
    rect = fitz.Rect(rect)
    if rotation is not None:
        if not isfinite(rotation) or abs(rotation) > 360:
            raise ValueError("Choose a finite angle between -360 and 360 degrees.")
        ap, matrix, bbox = _appearance(page, annot)
        old = bbox * matrix
        if old.is_empty or bbox.is_empty:
            raise ValueError("The stamp appearance has no usable size.")
        sx, sy = rect.width / old.width, rect.height / old.height
        current = degrees(atan2(matrix.b, matrix.a))
        matrix *= fitz.Matrix(rotation + page.rotation - current)
        size = bbox * matrix
        centre = (rect.tl + rect.br) / 2
        rect = fitz.Rect(centre.x - size.width * sx / 2, centre.y - size.height * sy / 2,
                         centre.x + size.width * sx / 2, centre.y + size.height * sy / 2)
    bounds = page.rect * page.derotation_matrix
    if not (bounds + (-.01, -.01, .01, .01)).contains(rect):
        raise ValueError("The rotated stamp extends outside the page. Move it inward or reduce its size.")
    # Write native /Rect directly. Annot.update() would regenerate the native
    # appearance and round its rotation to whole degrees (or rotate it again).
    page_rotation = page.rotation
    try:
        page.set_rotation(0)
        pdf_rect = rect * ~page.transformation_matrix
    finally:
        page.set_rotation(page_rotation)
    doc.xref_set_key(annot.xref, "Rect", "[" + " ".join(f"{v:.9f}" for v in pdf_rect) + "]")
    if rotation is not None:
        # Appearance streams may be shared after page duplication. Keep edits
        # local, including the matrix, and preserve the original vector content.
        new_ap = doc.get_new_xref()
        doc.update_object(new_ap, doc.xref_object(ap))
        doc.update_stream(new_ap, doc.xref_stream(ap))
        doc.xref_set_key(new_ap, "Matrix", "[" + " ".join(f"{v:.9f}" for v in matrix) + "]")
        kind, ap_value = doc.xref_get_key(annot.xref, "AP")
        ap_dictionary = doc.xref_object(int(ap_value.split()[0])) if kind == "xref" else ap_value
        owned_dictionary = doc.get_new_xref()
        doc.update_object(owned_dictionary, ap_dictionary)
        doc.xref_set_key(owned_dictionary, "N", f"{new_ap} 0 R")
        doc.xref_set_key(annot.xref, "AP", f"{owned_dictionary} 0 R")
        doc.xref_set_key(annot.xref, "Rotate", "0")
    return int(annot.xref)
