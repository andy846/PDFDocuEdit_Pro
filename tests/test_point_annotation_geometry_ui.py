"""Real Qt drag and Viewer transaction coverage for native point annotations."""
from __future__ import annotations

import fitz
import pytest
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtTest import QTest

from core.annotations import list_annotations, update_annotation_geometry
from tests.test_annotation_transactions import annotation_app as annotation_app
from tests.test_annotation_transactions import viewer as viewer
from tests.test_point_annotation_geometry import KINDS, assert_points, groups, make_annotation
from ui.page_overlay import PageOverlay


def document_points(doc, xref):
    page = doc[0]  # retain Page while reading Annot's weak parent reference
    return groups(page.load_annot(xref))


def saved_pixels(doc):
    # Transactions serialize their backup. Compare the same PDF precision on
    # both sides, rather than in-memory floats versus rounded PDF numbers.
    with fitz.open(stream=doc.tobytes(no_new_id=True), filetype="pdf") as saved:
        return saved[0].get_pixmap().samples


@pytest.mark.parametrize("kind", KINDS)
def test_point_drag_clamps_move_and_retains_last_valid_resize(qt_application, kind):
    overlay = PageOverlay(0)
    pixmap = QPixmap(400, 350)
    pixmap.fill()
    overlay.set_pixmap(pixmap)
    overlay.set_geometry_info(fitz.Rect(0, 0, 400, 350), 1.)
    entry = {"kind": kind, "xref": 10, "rect": (60, 60, 190, 130)}
    overlay._begin_geometry_drag(entry, QPointF(100, 95))
    overlay._update_geometry_drag(QPointF(-500, -500))
    rect = overlay._geometry_drag["rect"]
    assert rect.left() == 0 and rect.top() == 0
    assert rect.width() == 130 and rect.height() == 70
    overlay._begin_geometry_drag(entry, QPointF(190, 130))
    overlay._update_geometry_drag(QPointF(220, 170))
    valid = QRectF(overlay._geometry_drag["rect"])
    assert valid.width() == 160 and valid.height() == 110  # no image aspect lock
    overlay._update_geometry_drag(QPointF(800, 800))
    assert overlay._geometry_drag["rect"] == valid
    payload = overlay._finish_geometry_drag(QPointF(800, 800))
    assert tuple(payload["rect"]) == pytest.approx((60, 60, 220, 170))
    overlay.close()


@pytest.mark.parametrize("kind", KINDS)
def test_viewer_edit_undo_redo_and_save_reopen(viewer, tmp_path, kind):
    window = viewer
    page = window.engine.document[0]
    annot = make_annotation(page, kind)
    xref = annot.xref
    before = groups(annot)
    pixels = saved_pixels(window.engine.document)
    source = window.engine.original_path.read_bytes()
    window._change_annotation_geometry(window._session, 0, xref,
                                       {"rect": fitz.Rect(280, 260, 460, 380)})
    moved = document_points(window.engine.document, xref)
    assert moved != before
    assert window._undo_stack.undo_count == 1
    after_pixels = saved_pixels(window.engine.document)
    assert after_pixels != pixels
    assert window._undo()
    assert_points(document_points(window.engine.document, xref), before)
    assert saved_pixels(window.engine.document) == pixels
    assert window._redo()
    assert_points(document_points(window.engine.document, xref), moved)
    assert saved_pixels(window.engine.document) == after_pixels
    for canvas in window._session_canvases(window._session):
        assert canvas._doc is window.engine.document
    path = tmp_path / "edited.pdf"
    window.engine.document.save(path)
    with fitz.open(path) as saved:
        assert saved[0].get_pixmap().samples == after_pixels
    assert window.engine.original_path.read_bytes() == source


@pytest.mark.parametrize("failure", ["update", "readback", "appearance", "missing"])
def test_viewer_failure_restores_pixels_history_and_reports_reason(viewer, monkeypatch, failure):
    window = viewer
    page = window.engine.document[0]
    annot = make_annotation(page, "Ink")
    xref = annot.xref
    points = groups(annot)
    if failure == "appearance":
        page.parent.xref_set_key(xref, "AP/R", page.parent.xref_get_key(xref, "AP/N")[1])
    before = window.engine.document[0].get_pixmap().samples
    window._undo_stack.push_redo(str(window.engine.temp_path), "Existing redo")
    messages = []
    monkeypatch.setattr(window.info_bar, "show_message", lambda *args: messages.append(args[0]))
    if failure in {"update", "readback"}:
        original = fitz.Annot.update
        def broken(target, *args, **kwargs):
            if failure == "update":
                raise RuntimeError("injected update failure")
            original(target, *args, **kwargs)
            doc = target.parent.parent
            doc.xref_set_key(target.xref, "InkList", "[[60 760 95 730 150 755]]")
        monkeypatch.setattr(fitz.Annot, "update", broken)
    window._change_annotation_geometry(window._session, 0, xref if failure != "missing" else 999999,
                                       {"rect": fitz.Rect(280, 260, 460, 380)})
    assert window.engine.document[0].get_pixmap().samples == before
    assert_points(document_points(window.engine.document, xref), points)
    assert not window.engine.is_modified
    assert window._undo_stack.undo_count == 0
    assert window._undo_stack.redo_descriptions() == ["Existing redo"]
    assert messages and "Move/resize failed" in messages[-1]
    if failure == "readback":
        assert "geometry verification failed" in messages[-1]
    if failure == "appearance":
        assert "unsupported appearance" in messages[-1]
    for canvas in window._session_canvases(window._session):
        assert canvas._doc is window.engine.document


def test_error_detail_does_not_claim_restore_when_rollback_failed():
    from core.viewer import PDFViewer
    error = RuntimeError("PDF operation failed and rollback also failed.")
    error.__cause__ = RuntimeError("rollback reader failure")
    assert PDFViewer._image_failure_detail(error) == str(error)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("zoom", [.75, 1.5])
def test_real_mouse_drag_commits_only_on_release(qt_application, kind, rotation, zoom):
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        page.set_cropbox(fitz.Rect(20, 30, 555, 792))
        page.set_rotation(rotation)
        annot = make_annotation(page, kind)
        xref, old = annot.xref, fitz.Rect(annot.rect)
        overlay = PageOverlay(0)
        pixmap = QPixmap(round(page.rect.width * zoom), round(page.rect.height * zoom))
        pixmap.fill()
        overlay.set_pixmap(pixmap)
        overlay.set_geometry_info(page.rect, 1 / zoom, page.rotation_matrix, page.derotation_matrix)
        overlay.set_annotations(list_annotations(page))
        overlay.select_annotation(xref)
        overlay.show()
        qt_application.processEvents()
        calls = []
        errors = []
        def commit(number, selected, payload):
            calls.append((number, selected, payload))
            try:
                update_annotation_geometry(page, selected, rect=payload["rect"])
            except Exception as exc:
                errors.append(exc)  # never let an exception escape a Qt slot
        overlay.annotationGeometryChanged.connect(commit)
        start = overlay.pdf_rect_to_widget(old).center().toPoint()
        end = start + QPointF((40 if start.x() < overlay.width() / 2 else -40) * zoom,
                             (40 if start.y() < overlay.height() / 2 else -40) * zoom).toPoint()
        before = doc.tobytes(no_new_id=True)
        QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(overlay, end)
        assert not calls and doc.tobytes(no_new_id=True) == before
        QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=end)
        assert not errors
        assert len(calls) == 1 and calls[0][1] == xref
        visible = page.load_annot(xref).rect * page.rotation_matrix
        original = old * page.rotation_matrix
        assert visible.x0 - original.x0 == pytest.approx((end.x() - start.x()) / zoom, abs=.02)
        assert visible.y0 - original.y0 == pytest.approx((end.y() - start.y()) / zoom, abs=.02)
        overlay.close()
