"""Point-based annotation edits must change native geometry and appearance."""
from __future__ import annotations

import fitz
import numpy as np
import pytest

from core.annotations import AnnotationValidationError, list_annotations, update_annotation_geometry

KINDS = ("Highlight", "Underline", "StrikeOut", "Squiggly", "Ink", "Polygon")


def make_annotation(page, kind):
    if kind == "Ink":
        annot = page.add_ink_annot([[(60, 60), (95, 90), (150, 65)], [(70, 110), (190, 120)]])
    elif kind == "Polygon":
        annot = page.add_polygon_annot([(60, 60), (180, 70), (145, 100), (190, 130), (80, 120)])
    else:
        quads = [fitz.Quad((60, 60), (190, 64), (58, 78), (188, 82)),
                 fitz.Rect(62, 95, 160, 113).quad]
        method = {"Highlight": page.add_highlight_annot, "Underline": page.add_underline_annot,
                  "StrikeOut": page.add_strikeout_annot, "Squiggly": page.add_squiggly_annot}[kind]
        annot = method(quads)
    annot.set_colors(stroke=(.8, .1, .2), **({"fill": (.1, .7, .2)} if kind == "Polygon" else {}))
    if kind in {"Ink", "Polygon"}:
        annot.set_border(width=2)
    annot.set_opacity(.45)
    annot.set_info(title="QA author", content="QA note", subject="QA geometry")
    annot.set_flags(fitz.PDF_ANNOT_IS_PRINT)
    annot.update()
    return annot


def groups(annot):
    return annot.vertices if annot.type[1] == "Ink" else [annot.vertices]


def transform(points, old, target):
    return [[(target.x0 + (x - old.x0) * target.width / old.width,
              target.y0 + (y - old.y0) * target.height / old.height) for x, y in stroke] for stroke in points]


def assert_points(actual, expected):
    assert len(actual) == len(expected)
    for stroke, wanted in zip(actual, expected, strict=True):
        assert len(stroke) == len(wanted)
        for point, want in zip(stroke, wanted, strict=True):
            assert tuple(point) == pytest.approx(tuple(want), abs=.01)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("cropped", [False, True])
@pytest.mark.parametrize("scale", [(1, 1), (1.3, 1.3), (.6, 1.4)])
def test_native_points_xref_style_and_saved_output(kind, rotation, cropped, scale):
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        if cropped:
            page.set_cropbox(fitz.Rect(20, 30, 555, 792))
        page.set_rotation(rotation)
        annot = make_annotation(page, kind)
        xref, old = annot.xref, fitz.Rect(annot.rect)
        expected_info, colors, flags = dict(annot.info), dict(annot.colors), annot.flags
        border = dict(annot.border)
        source = groups(annot)
        target = fitz.Rect(old.x0 + 100, old.y0 + 140,
                           old.x0 + 100 + old.width * scale[0], old.y0 + 140 + old.height * scale[1])
        expected = transform(source, old, target)
        assert update_annotation_geometry(page, xref, rect=target) == xref
        moved = page.load_annot(xref)  # caller's Page must remain usable
        assert_points(groups(moved), expected)
        assert moved.info == expected_info and moved.colors == colors and moved.flags == flags
        assert moved.opacity == pytest.approx(.45) and moved.border == border
        assert page.rotation == rotation
        with fitz.open(stream=doc.tobytes(), filetype="pdf") as saved:
            saved_page = saved[0]
            restored = saved_page.load_annot(xref)
            assert restored.type[1] == kind
            assert_points(groups(restored), expected)
            assert restored.info == expected_info


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("indirect", [False, True])
def test_shared_appearance_is_never_modified(kind, indirect):
    with fitz.open() as doc:
        page = doc.new_page()
        first, second = make_annotation(page, kind), make_annotation(page, kind)
        first_xref, second_xref = first.xref, second.xref
        if indirect:
            dictionary = doc.get_new_xref()
            doc.update_object(dictionary, doc.xref_get_key(first_xref, "AP")[1])
            for xref in (first_xref, second_xref):
                doc.xref_set_key(xref, "AP", f"{dictionary} 0 R")
        else:
            doc.xref_set_key(second_xref, "AP", doc.xref_get_key(first_xref, "AP")[1])
        normal = int(doc.xref_get_key(first_xref, "AP/N")[1].split()[0])
        before_stream, before_object = doc.xref_stream(normal), doc.xref_object(normal)
        before_points = groups(page.load_annot(first_xref))
        target = fitz.Rect(second.rect) + (100, 140, 140, 180)
        update_annotation_geometry(page, second_xref, rect=target)
        assert doc.xref_stream(normal) == before_stream and doc.xref_object(normal) == before_object
        assert_points(groups(page.load_annot(first_xref)), before_points)
        assert int(doc.xref_get_key(second_xref, "AP/N")[1].split()[0]) != normal


def test_ink_list_preserves_strokes_without_changing_flat_vertices_contract():
    with fitz.open() as doc:
        page = doc.new_page()
        annot = make_annotation(page, "Ink")
        entry = next(row for row in list_annotations(page) if row["xref"] == annot.xref)
        assert_points(entry["ink_strokes"], annot.vertices)
        assert entry["vertices"] == []


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("target", [(-20, 50, 100, 150), (0, 0, .1, 100), (0, 0, float("nan"), 100)])
def test_invalid_target_rejected_before_any_write(kind, target):
    with fitz.open() as doc:
        page = doc.new_page()
        annot = make_annotation(page, kind)
        before = doc.tobytes(no_new_id=True)
        with pytest.raises(AnnotationValidationError):
            update_annotation_geometry(page, annot.xref, rect=fitz.Rect(target))
        assert doc.tobytes(no_new_id=True) == before


@pytest.mark.parametrize("field", ["R", "D"])
def test_unsupported_appearance_states_rejected_without_changes(field):
    with fitz.open() as doc:
        page = doc.new_page()
        annot = make_annotation(page, "Highlight")
        doc.xref_set_key(annot.xref, "AP/" + field, doc.xref_get_key(annot.xref, "AP/N")[1])
        before = doc.tobytes(no_new_id=True)
        with pytest.raises(AnnotationValidationError, match="appearance"):
            update_annotation_geometry(page, annot.xref, rect=fitz.Rect(250, 250, 450, 400))
        assert doc.tobytes(no_new_id=True) == before


def painted_bounds(page, zoom):
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    pixels = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    ys, xs = np.where(np.min(pixels[:, :, :3], axis=2) < 245)
    assert len(xs)
    return fitz.Rect(xs.min() / zoom, ys.min() / zoom,
                     (xs.max() + 1) / zoom, (ys.max() + 1) / zoom)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("zoom", [1, 2])
@pytest.mark.parametrize("scale", [(1, 1), (.7, 1.4)])
def test_rendered_location_proportions_and_reopen(kind, rotation, zoom, scale):
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        page.set_cropbox(fitz.Rect(20, 30, 555, 792))
        page.set_rotation(rotation)
        annot = make_annotation(page, kind)
        old = fitz.Rect(annot.rect)
        before = painted_bounds(page, zoom) * page.derotation_matrix
        target = fitz.Rect(250, 300, 250 + old.width * scale[0], 300 + old.height * scale[1])
        update_annotation_geometry(page, annot.xref, rect=target)
        actual = painted_bounds(page, zoom) * page.derotation_matrix
        expected = transform([[(before.x0, before.y0), (before.x1, before.y1)]], old, target)[0]
        # MuPDF regenerates fixed-width strokes / markup padding, rather than
        # scaling border thickness. Allow 3pt, but never a stale old position.
        assert tuple(actual) == pytest.approx((*expected[0], *expected[1]), abs=3)
        assert not actual.intersects(before)
        pixels = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).samples
        with fitz.open(stream=doc.tobytes(), filetype="pdf") as saved:
            assert saved[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom)).samples == pixels


@pytest.mark.parametrize("kind,key,value", [
    ("Ink", "InkList", "[[60 760]]"),
    ("Polygon", "Vertices", "[60 760 90 730]"),
    ("Highlight", "QuadPoints", "[60 760 90 730 100 720]"),
    ("Highlight", "QuadPoints", "[60 760 60 760 60 760 60 760]"),
])
def test_invalid_native_points_rejected_before_any_write(kind, key, value):
    with fitz.open() as doc:
        page = doc.new_page()
        annot = make_annotation(page, kind)
        doc.xref_set_key(annot.xref, key, value)
        before = doc.tobytes(no_new_id=True)
        with pytest.raises(AnnotationValidationError, match="invalid geometry"):
            update_annotation_geometry(page, annot.xref, rect=fitz.Rect(250, 300, 400, 400))
        assert doc.tobytes(no_new_id=True) == before
