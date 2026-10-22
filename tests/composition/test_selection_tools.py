from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import asdict

import fitz
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontDatabase, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from composition.engine.assets import asset_root
from composition.engine.renderer import render_preview
from composition.overlay.renderer import render_preview as overlay_preview
from composition.template.model import Element
from styles.theme import apply_theme
from tests.composition.test_batch_edit import bounded_ui, cleanup, setup_window  # noqa: F401


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("overlay", [False, True])
def test_type_filter_select_current_page_and_bidirectional_layers(app, tmp_path, overlay):
    window = setup_window(tmp_path, overlay)
    try:
        window.layer_type.setCurrentIndex(window.layer_type.findData("text"))
        visible = [window.layers.item(i) for i in range(window.layers.count()) if not window.layers.item(i).isHidden()]
        assert len(visible) == (1 if overlay else 2)
        window.actions["select_type"].trigger()
        text_ids = {item.element.id for item in window.canvas.element_items if item.element.type == "text"}
        assert set(window.canvas.selected_ids()) == text_ids
        assert {i.data(Qt.ItemDataRole.UserRole) for i in window.layers.selectedItems()} == text_ids
        window.layer_type.setCurrentIndex(0)
        barcode = next(item for item in window.canvas.element_items if item.element.type == "code128")
        window.canvas.select_ids([barcode.element.id])
        window.actions["select_type"].trigger()
        assert window.canvas.selected_ids() == [barcode.element.id]
    finally:
        cleanup(window)


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("overlay", [False, True])
def test_batch_preserves_view_preview_scroll_and_narrow_inspector(app, tmp_path, theme, overlay):
    previous_font = QFont(app.font())
    font_id = QFontDatabase.addApplicationFont(str(asset_root()/"fonts"/"NotoSans-Regular.ttf"))
    app.setFont(QFont("Noto Sans", 9))
    apply_theme(app, theme)
    window = setup_window(tmp_path, overlay)
    try:
        if not overlay:
            page = window.template.to_dict()
            page["pages"][0]["elements"] += [asdict(Element(value=f"Layer {i}", y_mm=190+i)) for i in range(30)]
            window._apply_template(page)
            window.left_panel.setCurrentIndex(1)
        else:
            page = window.spec.to_dict()
            original = page["objects"][0]
            import copy
            for i in range(30):
                obj = copy.deepcopy(original)
                obj["element"].update(id=f"layer_{i}", value=f"Layer {i}", y_mm=190+i)
                page["objects"].append(obj)
            window.apply_spec(page)
            window.source_panels.setCurrentIndex(1)
        window.show()
        window.resize(960, 640)
        QTest.qWait(100)
        window.canvas.set_zoom(1.6)
        window.canvas.horizontalScrollBar().setValue(20)
        window.canvas.verticalScrollBar().setValue(30)
        ids = [item.element.id for item in window.canvas.element_items[:2]]
        window.canvas.select_ids(ids)
        window.layers.verticalScrollBar().setValue(window.layers.verticalScrollBar().maximum())
        QTest.qWait(50)
        image = QImage(100, 100, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        path = tmp_path / "preview.png"
        assert image.save(str(path))
        window.canvas.set_preview(str(path))
        preview = window.canvas.preview_item
        transform = window.canvas.transform()
        pan = (window.canvas.horizontalScrollBar().value(), window.canvas.verticalScrollBar().value())
        scroll = window.layers.verticalScrollBar().value()
        generation = window.preview_generation
        window.properties.numbers["font_size"].setValue(16)
        assert window.batch_editor.apply()
        assert window.preview_generation == generation+1
        assert window.canvas.preview_item is preview and window.canvas.transform() == transform
        assert (window.canvas.horizontalScrollBar().value(), window.canvas.verticalScrollBar().value()) == pan
        assert window.layers.verticalScrollBar().value() == scroll
        assert set(window.canvas.selected_ids()) == set(ids)
        QTest.qWait(30)
        area = window.inspector_scroll if overlay else window.properties_scroll
        assert area.horizontalScrollBar().maximum() == 0
        area.ensureWidgetVisible(window.properties.geometry_apply, 0, 8)
        assert window.properties.geometry_apply.isVisible() and window.canvas.viewport().width() >= 180
        assert window.actions["undo"].isEnabled()
        window.properties.numbers["font_size"].setValue(17)
        assert not window.actions["undo"].isEnabled()
        window.batch_editor.revert()
        assert window.actions["undo"].isEnabled()
    finally:
        cleanup(window)
        app.setFont(previous_font)
        apply_theme(app, "system")
        QFontDatabase.removeApplicationFont(font_id)


@pytest.mark.parametrize("overlay", [False, True])
def test_batch_font_geometry_reaches_actual_pdf(app, tmp_path, overlay):
    window = setup_window(tmp_path, overlay)
    try:
        window.properties.numbers["font_size"].setValue(16)
        window.properties.numbers["width_mm"].setValue(85)
        assert window.batch_editor.apply()
        if overlay:
            pdf_bytes, _ = overlay_preview(window.spec, 1, 1)
        else:
            pdf_bytes = render_preview(window.template, {"Name": "Customer"})
        with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
            spans = [s for block in pdf[0].get_text("dict")["blocks"] for line in block.get("lines", []) for s in line["spans"]]
            assert any(s["size"] == pytest.approx(16) for s in spans)
        assert all(item.element.width_mm == 85 for item in window.canvas.element_items)
    finally:
        cleanup(window)


def test_200_percent_inspector_smoke_in_isolated_qt_process(tmp_path):
    # A fresh Qt process is required: scale is fixed when QApplication starts.
    script = r'''
from PyQt6.QtGui import QFont,QFontDatabase
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from composition.designer.workspace import CompositionWindow
from composition.designer.overlay_workspace import OverlayWindow
from composition.template.model import Element,Template
from styles.theme import apply_theme
from tests.composition.test_pdf_overlay_models import sample_spec
from pathlib import Path
from composition.engine.assets import asset_root
app=QApplication([]);QFontDatabase.addApplicationFont(str(asset_root()/"fonts"/"NotoSans-Regular.ttf"));app.setFont(QFont("Noto Sans",9))
CompositionWindow._load_windows_fonts=lambda self:None
CompositionWindow._render_preview=lambda self:None
OverlayWindow.load_fonts=lambda self:None
OverlayWindow.render_preview=lambda self:None
for theme in ("dark","light"):
 apply_theme(app,theme)
 for overlay in (False,True):
  w=OverlayWindow() if overlay else CompositionWindow()
  if overlay:w.apply_spec(sample_spec(Path(__import__('sys').argv[1])).to_dict())
  else:w._apply_template(Template(elements=[Element(value="First"),Element(value="Second",y_mm=50)]).to_dict())
  w.show();w.resize(960,640);w.canvas.select_ids([i.element.id for i in w.canvas.element_items]);QTest.qWait(120)
  assert w.devicePixelRatioF()==2
  area=w.inspector_scroll if overlay else w.properties_scroll
  assert area.horizontalScrollBar().maximum()==0,(theme,overlay,area.width(),area.horizontalScrollBar().maximum())
  assert w.properties.geometry_apply.isVisible() and w.canvas.viewport().width()>=180
  w.undo.setClean();w._close_approved=True;w.close();QTest.qWait(20)
print("four scaled workspace/theme checks passed")
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_SCALE_FACTOR": "2"},
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    assert result.returncode == 0, result.stdout+result.stderr
