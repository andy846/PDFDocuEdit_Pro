"""Navigation behaviour, saved preferences and compact sidebar usability."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QWidget

from ui.side_panel import CATEGORY_LAYOUT, SidePanel
from ui.tool_navigation import FavouritesDialog


@pytest.fixture
def panel(qt_application):
    prefs = QSettings()
    prefs.remove("sidebar/v2")
    host = QWidget()
    host.resize(360, 640)
    sidebar = SidePanel(animations_enabled=False, parent=host)
    sidebar.resize(272, 600)
    host.show()
    sidebar.show()
    qt_application.processEvents()
    yield sidebar
    host.close()
    host.deleteLater()
    qt_application.processEvents()
    prefs.remove("sidebar/v2")


def test_categories_preserve_all_tools_exactly_once(panel):
    keys = [item.key for _key, _title, items in panel.SECTIONS for item in items]
    assert len(keys) == len(set(keys)) == 51
    assert set(keys) == set(panel._buttons)
    assert len(panel._rail_buttons) == 6
    assert all(not section._logical_expanded for section in panel._sections)
    assert panel._favourite_keys == list(panel.DEFAULT_FAVOURITES)


def test_branded_header_and_keyboard_toggle_fit_both_panel_widths(panel, qt_application):
    assert panel._title.text() == "PDF Workspace"
    assert panel._brand_mark.isVisible() and panel._subtitle.isVisible()
    assert not panel._brand_mark.pixmap().isNull()
    panel._toggle.setFocus()
    changes = []
    panel.collapsedChanged.connect(changes.append)
    QTest.keyClick(panel._toggle, Qt.Key.Key_Space)
    qt_application.processEvents()
    assert panel.is_collapsed() and changes == [True]
    assert panel.width() == 52
    assert not panel._brand_mark.isVisible() and not panel._brand_copy.isVisible()
    assert panel._header.rect().contains(panel._toggle.geometry())
    assert "Expand" in panel._toggle.accessibleName()
    QTest.keyClick(panel._toggle, Qt.Key.Key_Space)
    qt_application.processEvents()
    assert not panel.is_collapsed() and changes == [True, False]
    assert panel.width() == 272 and panel._brand_copy.isVisible()
    assert panel._header.rect().contains(panel._toggle.geometry())
    assert "Collapse" in panel._toggle.accessibleName()


def test_header_mark_has_foreground_contrast_when_theme_changes(panel, qt_application):
    from styles.theme import apply_theme, get_color
    from ui.icons import clear_icon_cache

    try:
        for theme in ("dark", "light"):
            apply_theme(qt_application, theme)
            clear_icon_cache()
            panel.refresh_icons()
            image = panel._brand_mark.pixmap().toImage()
            opaque = [image.pixelColor(x, y) for x in range(image.width()) for y in range(image.height())
                      if image.pixelColor(x, y).alpha() == 255]
            assert opaque and all(pixel.name() == get_color("text_primary") for pixel in opaque)
    finally:
        apply_theme(qt_application, "system")
        clear_icon_cache()


def test_favourites_persist_order_ignore_unknown_and_keep_empty(panel, qt_application):
    panel.set_favourites(["rotate", "merge", "rotate", "unknown", None])
    second = SidePanel(animations_enabled=False)
    assert second._favourite_keys == ["rotate", "merge"]
    panel.set_favourites([])
    third = SidePanel(animations_enabled=False)
    assert third._favourite_keys == []
    assert not panel._edit_favourites.isHidden()
    second.deleteLater()
    third.deleteLater()
    qt_application.processEvents()


def test_favourites_limit_and_availability_match_sources(panel):
    panel.set_favourites(list(panel._items))
    assert len(panel._favourite_keys) == 8
    assert not panel._favourite_buttons["search"].isEnabled()
    panel.set_document_available(True)
    assert panel._favourite_buttons["search"].isEnabled()
    panel.set_document_available(False, unavailable_hint="Choose the PDF tab first")
    assert "Choose the PDF tab first" in panel._favourite_buttons["search"].toolTip()


def test_search_aliases_shortcut_override_and_restore_sections(panel, qt_application):
    section = panel._sections[1]
    section.header.click()
    panel._search.setText("flatten")
    qt_application.processEvents()
    assert not panel._buttons["pdf_production"].isHidden()
    assert panel._favourites.isHidden()
    assert panel._buttons["merge"].isHidden()
    panel.set_shortcut_hints({"rotate": "Ctrl+Alt+6"})
    panel._search.setText("Ctrl+Alt+6")
    qt_application.processEvents()
    assert not panel._buttons["rotate"].isHidden()
    panel._search.setText("F6")
    assert panel._buttons["rotate"].isHidden()
    panel._search.setText("合併")
    assert not panel._buttons["merge"].isHidden()
    panel._search.setText("nothing-matches-this")
    assert not panel._tool_count.isHidden()
    panel._search.clear()
    qt_application.processEvents()
    assert section._logical_expanded
    assert not section.body.isHidden()
    assert panel._tool_count.isHidden()


def test_compact_categories_and_scroll_keep_every_entry_reachable(panel, qt_application):
    panel.set_favourites(list(panel._items)[:8])
    panel.set_collapsed(True, animate=False)
    panel.resize(52, 280)
    qt_application.processEvents()
    assert panel.width() == 52
    assert all(section.isHidden() for section in panel._sections)
    assert panel._scroll.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    assert panel._scroll.verticalScrollBar().maximum() > 0
    assert not panel._compact_search.isHidden()
    assert panel._search.isHidden()
    last = panel._rail_buttons["protection"]
    panel._scroll.ensureWidgetVisible(last)
    qt_application.processEvents()
    assert panel._scroll.verticalScrollBar().value() > 0
    assert all(not button.text() for button in panel._favourite_buttons.values())
    panel.set_collapsed(False, animate=False)
    qt_application.processEvents()
    assert panel.width() == 272
    assert panel._rail.isHidden()


def test_popup_keyboard_search_routing_and_screen_bounds(panel, qt_application):
    panel.set_document_available(True)
    panel.set_collapsed(True, animate=False)
    emitted = []
    panel.toolRequested.connect(emitted.append)
    panel._compact_search.click()
    qt_application.processEvents()
    popup = panel._popup
    assert popup.screen().availableGeometry().contains(popup.geometry())
    popup.search.setText("Merge PDFs")
    QTest.keyClick(popup.search, Qt.Key.Key_Down)
    assert popup.buttons["merge"].hasFocus()
    QTest.keyClick(popup.buttons["merge"], Qt.Key.Key_Return)
    assert emitted == ["merge"]
    assert not popup.isVisible()
    assert panel._active_key is None
    panel._rail_buttons["documents"].click()
    assert set(panel._popup.buttons) == set(CATEGORY_LAYOUT[1][3])
    QTest.keyClick(panel._popup.search, Qt.Key.Key_Escape)
    assert not panel._popup.isVisible()


def test_popup_enter_skips_disabled_tools_and_refreshes_availability(panel, qt_application):
    emitted = []
    panel.toolRequested.connect(emitted.append)
    panel._open_popup("documents", panel._toggle)
    popup = panel._popup
    popup.search.setText("rotate")
    QTest.keyClick(popup.search, Qt.Key.Key_Return)
    assert emitted == []
    assert not popup.buttons["rotate"].isEnabled()
    panel.set_document_available(True)
    assert popup.buttons["rotate"].isEnabled()
    QTest.keyClick(popup.search, Qt.Key.Key_Return)
    assert emitted == ["rotate"]


def test_active_tool_consistent_across_favourites_and_dialog_actions(panel):
    panel.set_document_available(True)
    panel.set_favourites(["highlight", "merge"])
    panel._favourite_buttons["highlight"].click()
    assert panel._buttons["highlight"].isChecked()
    assert panel._favourite_buttons["highlight"].isChecked()
    assert panel._rail_buttons["edit"].property("active")
    panel._favourite_buttons["merge"].click()
    assert not panel._favourite_buttons["merge"].isChecked()
    assert panel._active_key == "highlight"
    panel.set_active_tool(None)
    assert not panel._favourite_buttons["highlight"].isChecked()


def test_search_keyboard_does_not_need_mouse(panel, qt_application):
    panel.set_document_available(True)
    emitted = []
    panel.toolRequested.connect(emitted.append)
    panel._search.setText("extract pages")
    qt_application.processEvents()
    QTest.keyClick(panel._search, Qt.Key.Key_Return)
    assert emitted == ["extract"]
    QTest.keyClick(panel._search, Qt.Key.Key_Escape)
    assert panel._search.text() == ""


def test_dialog_add_remove_order_and_limit(panel):
    dialog = FavouritesDialog(panel._items, panel.DEFAULT_FAVOURITES, panel)
    original = dialog.keys()
    dialog.selected.setCurrentRow(0)
    dialog.move_tool(1)
    assert dialog.keys()[:2] == original[1::-1]
    dialog.remove_tool()
    assert original[0] not in dialog.keys()
    while dialog.selected.count() < 8:
        dialog.available.setCurrentRow(0)
        dialog.add_tool()
    dialog.available.setCurrentRow(0)
    dialog.add_tool()
    assert len(dialog.keys()) == 8
    assert "maximum" in dialog.message.text()
    dialog.deleteLater()


def test_elision_full_tooltip_and_old_preferences_left_intact(panel, qt_application):
    button = panel._buttons["barcode_batch"]
    panel._search.setText("batch read")
    button.setMaximumWidth(120)
    qt_application.processEvents()
    assert button.full_label in button.toolTip()
    assert button.accessibleName() == button.full_label
    assert button.text() != button.full_label
    QSettings().setValue("sidebar/section/pages", True)
    section = panel._sections[1]
    section.header.click()
    assert QSettings().value("sidebar/section/pages", False, bool)
    assert QSettings().contains("sidebar/v2/section/documents")


def test_repeated_popups_theme_refresh_and_animation_toggle(panel, qt_application):
    for _ in range(12):
        panel.set_collapsed(True, animate=False)
        panel._compact_search.click()
        panel.refresh_icons()
        panel._popup.search.setText("font")
        panel.set_collapsed(False, animate=False)
        qt_application.processEvents()
        assert not panel._popup.isVisible()
    panel.set_animations_enabled(True)
    section = panel._sections[0]
    section.header.click()
    panel.set_collapsed(True)
    panel.set_animations_enabled(False)
    assert panel.width() == 52
    assert section._animation.state() == section._animation.State.Stopped


def test_compact_favourites_remain_available_with_saved_search(panel):
    panel._search.setText("rotate")
    panel.set_collapsed(True, animate=False)
    assert not panel._favourites.isHidden()
    assert panel._search.text() == "rotate"
    panel.set_collapsed(False, animate=False)
    assert panel._favourites.isHidden()


def test_description_search_and_dialog_keeps_confirmation_visible(panel, qt_application):
    panel._search.setText("permanently remove sensitive")
    assert not panel._buttons["redact"].isHidden()
    dialog = FavouritesDialog(panel._items, panel.DEFAULT_FAVOURITES, panel)
    dialog.resize(380, 320)
    dialog.show()
    qt_application.processEvents()
    from PyQt6.QtWidgets import QDialogButtonBox

    box = dialog.findChild(QDialogButtonBox)
    assert dialog.rect().contains(box.geometry())
    dialog.close()
    dialog.deleteLater()


def test_bottom_category_popup_stays_inside_screen(panel, qt_application):
    panel.set_collapsed(True, animate=False)
    panel._rail_buttons["production"].click()
    qt_application.processEvents()
    assert panel._popup.screen().availableGeometry().contains(panel._popup.frameGeometry())


def test_viewer_responsive_collapse_restores_saved_preference(qt_application, tmp_path, monkeypatch):
    import core.viewer as viewer_module
    from core.settings import SettingsManager

    settings = SettingsManager(tmp_path / "sidebar-settings.json")
    settings.set("animations_enabled", False)
    settings.set("left_panel_collapsed", False)
    monkeypatch.setattr(viewer_module, "SettingsManager", lambda: settings)
    window = viewer_module.PDFViewer()
    window.resize(960, 640)
    window.show()
    qt_application.processEvents()
    try:
        window._make_document_panel_room()
        assert window.side_panel.width() == 52
        assert window._auto_collapsed_sidebar
        assert not settings.get("left_panel_collapsed")
        window.resize(1280, 760)
        qt_application.processEvents()
        assert not window.side_panel.is_collapsed()
        assert not window._auto_collapsed_sidebar
        # Explicit user collapse survives subsequent window resizing.
        window.side_panel.set_collapsed(True, animate=False)
        window.resize(1400, 800)
        qt_application.processEvents()
        assert window.side_panel.is_collapsed()
        assert settings.get("left_panel_collapsed")
    finally:
        window.close()
        window.deleteLater()


def test_sidebar_navigation_does_not_modify_pdf(qt_application, tmp_path, monkeypatch):
    import core.viewer as viewer_module
    from core.pdf_backend import fitz
    from core.settings import SettingsManager

    settings = SettingsManager(tmp_path / "pdf-sidebar-settings.json")
    settings.set("animations_enabled", False)
    monkeypatch.setattr(viewer_module, "SettingsManager", lambda: settings)
    path = tmp_path / "source.pdf"
    with fitz.open() as doc:
        for _ in range(3):
            doc.new_page()
        doc.save(path)
    window = viewer_module.PDFViewer()
    window.resize(1280, 760)
    window.show()
    window._load_file_sync(str(path))
    window.goto_page(1)
    canvas = window.workspace.canvas
    canvas.set_zoom(1.1)
    qt_application.processEvents()
    state = (canvas.current_page, canvas.zoom_ratio, window.engine.revision, window.engine.is_modified)
    try:
        for _ in range(4):
            window.side_panel.set_collapsed(True, animate=False)
            window.side_panel._rail_buttons["documents"].click()
            window.side_panel._popup.hide()
            window.side_panel.set_collapsed(False, animate=False)
            qt_application.processEvents()
        assert (
            canvas.current_page,
            canvas.zoom_ratio,
            window.engine.revision,
            window.engine.is_modified,
        ) == state
    finally:
        window.close()
        window.deleteLater()
