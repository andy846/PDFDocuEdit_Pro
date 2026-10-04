from __future__ import annotations

import copy
from dataclasses import asdict

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox

from composition.designer.overlay_workspace import OverlayWindow
from composition.designer.workspace import CompositionWindow
from composition.template.model import Element, FontSpec, Template
from tests.composition.test_pdf_overlay_models import sample_spec
from tests.composition.test_pdf_overlay_ui import finish
from tests.composition.test_workspace import close_window


@pytest.fixture(scope="session")
def app(qt_application):
    return qt_application


@pytest.fixture(autouse=True)
def bounded_ui(monkeypatch):
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "load_fonts", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "render_preview", lambda self: None)


def setup_window(tmp_path, overlay):
    window = OverlayWindow() if overlay else CompositionWindow()
    if overlay:
        spec = sample_spec(tmp_path)
        spec.objects[0].element.glyph_repairs = {"U+7530": FontSpec()}
        spec.objects[1].element.show_barcode_text = True
        window.apply_spec(spec.to_dict())
    else:
        window._apply_template(Template(elements=[
            Element(value="{{Name}}", x_mm=20, y_mm=60, glyph_repairs={"U+7530": FontSpec()}),
            Element(value="Other {{Name}}", x_mm=30, y_mm=100, font=FontSpec(size_pt=15)),
            Element(type="code128", value="123456", x_mm=20, y_mm=160, show_barcode_text=True),
        ]).to_dict())
    window.undo.clear()
    window.canvas.select_ids([item.element.id for item in window.canvas.element_items])
    return window


def raw(window):
    return window.template.to_dict() if hasattr(window, "template") else window.spec.to_dict()


def cleanup(window):
    window.batch_editor.revert()
    (close_window if hasattr(window, "template") else finish)(window)


@pytest.mark.parametrize("overlay", [False, True])
def test_combined_draft_one_undo_preserves_payload_repairs_scope_and_selection(app, tmp_path, overlay):
    window = setup_window(tmp_path, overlay)
    try:
        before = raw(window)
        original = [asdict(i.element) for i in window.canvas.element_items]
        ids = window.canvas.selected_ids()
        assert len(window.properties.bulk_ids) == (1 if overlay else 2)
        window.canvas.set_zoom(1.4)
        page_item = window.canvas.page_item
        window.properties.numbers["font_size"].setValue(18)
        window.properties.numbers["font_size"].editingFinished.emit()
        window.properties.colour.setText("#123456")
        window.properties.numbers["width_mm"].setValue(85)
        window.properties.numbers["rotation_deg"].setValue(15)
        assert raw(window) == before and window.undo.count() == 0
        assert window.properties.has_batch_draft()
        assert window.batch_editor.apply()
        assert not window.properties.has_batch_draft() and window.undo.count() == 1
        for first, item in zip(original, window.canvas.element_items, strict=True):
            e = asdict(item.element)
            assert e["value"] == first["value"] and e["glyph_repairs"] == first["glyph_repairs"] and e["rules"] == first["rules"]
            assert e["rotation_deg"] == 15 and e["width_mm"] == 85
            if e["type"] == "text":
                assert e["font"]["size_pt"] == 18 and e["colour"] == "#123456"
            else:
                assert e["font"] == first["font"]
        assert set(window.canvas.selected_ids()) == set(ids) and window.canvas.page_item is page_item
        window.undo.undo()
        assert raw(window) == before
    finally:
        cleanup(window)


def test_mixed_display_and_explicit_barcode_targets(app, tmp_path):
    window = setup_window(tmp_path, False)
    try:
        assert window.properties.numbers["font_size"].lineEdit().placeholderText() == "Mixed"
        assert not window.properties.numbers["font_size"].lineEdit().text()
        window.properties.include_barcode.setChecked(True)
        assert len(window.properties.bulk_ids) == 3
        window.properties.numbers["font_size"].setValue(19)
        assert window.batch_editor.apply()
        assert all(e.font.size_pt == 19 for e in window.template.elements)
        assert window.template.elements[-1].value == "123456"
    finally:
        cleanup(window)


@pytest.mark.parametrize("overlay", [False, True])
def test_invalid_batch_and_failed_font_prepare_keep_draft_and_model(app, tmp_path, monkeypatch, overlay):
    window = setup_window(tmp_path, overlay)
    try:
        before = raw(window)
        window.properties.numbers["width_mm"].setValue(190)
        window.properties.numbers["font_size"].setValue(22)
        assert not window.batch_editor.apply()
        assert raw(window) == before and window.undo.count() == 0
        assert window.properties.has_batch_draft() and window.properties.numbers["font_size"].value() == 22
        window.batch_editor.revert()
        window.properties.numbers["font_size"].setValue(24)
        window.properties._emit_font_request({"file": "missing.ttf"})
        def failed_worker(request, ready, failed):
            QTimer.singleShot(0, lambda: failed("Cannot load exact font"))
        monkeypatch.setattr(window, "_worker" if not overlay else "worker", failed_worker)
        assert not window.batch_editor.apply(wait=True)
        assert raw(window) == before and window.undo.count() == 0
        assert window.properties.has_batch_draft() and window.properties.numbers["font_size"].value() == 24
    finally:
        cleanup(window)


def test_selection_cancel_and_discard_restore_draft_without_commits(app, tmp_path, monkeypatch):
    window = setup_window(tmp_path, False)
    try:
        ids = window.canvas.selected_ids()
        before = raw(window)
        window.properties.numbers["font_size"].setValue(20)
        monkeypatch.setattr(QMessageBox, "exec", lambda self: None)
        monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: None)
        window.canvas.select_ids([ids[0]])
        assert set(window.canvas.selected_ids()) == set(ids)
        assert window.properties.has_batch_draft() and raw(window) == before
        monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: next(b for b in self.buttons() if b.text() == "Discard"))
        window.canvas.select_ids([ids[0]])
        assert window.canvas.selected_ids() == [ids[0]] and not window.properties.has_batch_draft()
        assert raw(window) == before
    finally:
        cleanup(window)


def test_format_clipboard_cross_workspace_keeps_content_and_geometry(app, tmp_path, monkeypatch):
    template, overlay = setup_window(tmp_path, False), setup_window(tmp_path, True)
    try:
        template.template.elements[0].font.size_pt = 23
        template.canvas.select_ids([template.template.elements[0].id])
        template.batch_editor.copy_format()
        source = copy.deepcopy(template.batch_editor.clipboard.value)
        original = [asdict(item.element) for item in overlay.canvas.element_items]
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Apply)
        overlay.batch_editor.paste_format()
        assert overlay.undo.count() == 1
        for before, item in zip(original, overlay.canvas.element_items, strict=True):
            current = asdict(item.element)
            if current["type"] == "text":
                for k, v in source.items():
                    assert current[k] == v
            for k in ("value", "x_mm", "width_mm", "rotation_deg", "glyph_repairs", "rules"):
                assert current[k] == before[k]
    finally:
        cleanup(template)
        cleanup(overlay)


@pytest.mark.parametrize("overlay", [False, True])
def test_selection_apply_and_page_cancel(app, tmp_path, monkeypatch, overlay):
    window = setup_window(tmp_path, overlay)
    try:
        ids = window.canvas.selected_ids()
        window.properties.numbers["font_size"].setValue(21)
        monkeypatch.setattr(QMessageBox, "exec", lambda self: None)
        monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: next(b for b in self.buttons() if b.text() == "Apply"))
        window.canvas.select_ids([ids[0]])
        assert window.undo.count() == 1 and window.canvas.selected_ids() == [ids[0]]
        window.canvas.select_ids(ids)
        window.properties.numbers["font_size"].setValue(22)
        before = raw(window)
        monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: None)
        if overlay:
            old = window.envelope.value()
            window.envelope.setValue(old+1)
            assert window.envelope.value() == old
            window.save_project(path=str(tmp_path / "cancelled.pdcx"))
        else:
            old = window.tabs.currentIndex()
            window.tabs.setCurrentIndex(2)
            assert window.tabs.currentIndex() == old
            assert window.save_project() is False
        assert raw(window) == before and window.properties.has_batch_draft()
        assert not (tmp_path / "cancelled.pdcx").exists()
    finally:
        cleanup(window)


def test_exit_cancel_keeps_discarded_draft_in_earlier_tab(app, tmp_path, monkeypatch):
    from composition.designer.project_host import DesignerProjectHost
    host = DesignerProjectHost()
    first = host._append(setup_window(tmp_path, False))
    second = host.new_template()
    try:
        first.properties.numbers["font_size"].setValue(27)
        second.add_element("text", "Unsaved")
        monkeypatch.setattr(QMessageBox, "exec", lambda self: None)
        monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: next(b for b in self.buttons() if b.text() == "Discard"))
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
        assert not host.confirm_all()
        assert first.properties.has_batch_draft() and first.properties.numbers["font_size"].value() == 27
        assert first.undo.count() == 0 and not second.undo.isClean()
        assert not first.close_pending and not second.close_pending
    finally:
        for w in (first, second):
            w._close_approved = True
            cleanup(w)
        host.close()


def test_real_font_clipboard_owns_asset_after_source_close_and_save(app, tmp_path, monkeypatch):
    from composition.engine.fonts import resolve_font
    from composition.template.serializer import load_project, save_project
    from tests.composition.test_workspace import wait_until
    template, overlay = setup_window(tmp_path, False), setup_window(tmp_path, True)
    try:
        source = resolve_font(FontSpec())
        template.template.elements[0].font.file = str(source)
        template.canvas.select_ids([template.template.elements[0].id])
        template.batch_editor.copy_format()
        wait_until(lambda: not template.batch_editor.pending)
        copied = copy.deepcopy(template.batch_editor.clipboard.value)
        from pathlib import Path
        assert Path(copied["font"]["file"]).is_file()
        assert Path(copied["font"]["file"]).parent != template.directory
        cleanup(template)
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Apply)
        overlay.batch_editor.paste_format()
        face = overlay.spec.objects[0].element.font.file
        assert Path(face).is_file() and Path(face).is_relative_to(overlay.directory)
        saved = save_project(Template(elements=[overlay.spec.objects[0].element]), tmp_path / "font.pdcx")
        assert Path(load_project(saved).elements[0].font.file).is_file()
    finally:
        if not template.close_pending:
            cleanup(template)
        cleanup(overlay)


def test_font_callback_during_shutdown_never_commits_or_updates_ui(app, tmp_path, monkeypatch):
    window = setup_window(tmp_path, False)
    callbacks = []
    try:
        before = raw(window)
        window.properties._emit_font_request({"file": "pending.ttf"})
        monkeypatch.setattr(window, "_worker", lambda request, ready, failed: callbacks.append((ready, failed)))
        assert not window.batch_editor.apply()
        assert window.batch_editor.pending
        window.close_pending = True
        monkeypatch.setattr(window, "_busy", lambda: pytest.fail("UI updated during shutdown"))
        callbacks[0][0]({"faces": []})
        assert not window.batch_editor.pending and raw(window) == before and not window.undo.count()
        assert len(callbacks) == 1
    finally:
        window.close_pending = False
        cleanup(window)
