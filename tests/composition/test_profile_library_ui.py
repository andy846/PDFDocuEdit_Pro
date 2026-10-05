"""Library navigation and draft safety through the real background transport."""
import copy

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QFileDialog

from composition.designer.media_dialog import MediaDialog
from composition.designer.profile_library_dialog import ProfileLibraryDialog
from composition.media.profile_library import import_profiles
from styles.components import global_style
from styles.theme import apply_theme
from tests.composition.test_profile_library import profile, write
from tests.composition.test_workspace import wait_until


def test_library_background_import_filters_and_selected_profile(qt_application, tmp_path, monkeypatch):
    library = tmp_path / "library"
    sources = [write(tmp_path / f"{i}.json", profile(kind, family))
               for i, (kind, family) in enumerate((("media", "vp6000"), ("media", "ix"), ("printer", "ix")))]
    dialog = ProfileLibraryDialog(library)
    try:
        dialog.show()
        assert dialog.worker is not None and not dialog.use_button.isEnabled()
        wait_until(lambda: dialog.worker is None)
        assert dialog.profiles.count() == 0
        monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args: ([str(p) for p in sources], ""))
        dialog.import_files.click()
        assert dialog.worker is not None
        wait_until(lambda: dialog.worker is None)
        assert dialog.profiles.count() == 3 and "Imported 3" in dialog.status.text()
        dialog.device.setCurrentIndex(dialog.device.findData("ix"))
        assert dialog.profiles.count() == 2
        dialog.kind.setCurrentIndex(dialog.kind.findData("media"))
        assert dialog.profiles.count() == 1 and "within each letter" in dialog.details.toPlainText()
        assert "Replaces Stocks" in dialog.details.toPlainText()
        dialog.use_button.click()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.selected_profile["settings"]["printer_profile"]["family"] == "ix"
    finally:
        dialog.reject()
        wait_until(lambda: dialog.worker is None)


def test_cancel_and_template_mismatch_keep_current_media_draft(qt_application, tmp_path, monkeypatch):
    dialog = MediaDialog(profile()["settings"])
    try:
        before = copy.deepcopy(dialog.value())
        monkeypatch.setattr(dialog, "profile_directory", lambda: tmp_path)
        def cancel_library(library):
            wait_until(lambda: library.worker is None)
            library.reject()
            return QDialog.DialogCode.Rejected
        monkeypatch.setattr(ProfileLibraryDialog, "exec", cancel_library)
        dialog.open_library()
        assert dialog.value() == before
        invalid = profile()
        invalid["settings"].update(mode="template", assignments={"foreign_page": "LH_A"})
        with pytest.raises(ValueError, match="other template"):
            dialog.apply_library_profile(invalid)
        assert dialog.value() == before
        dialog.worker = object()
        dialog.navigation()
        assert not dialog.library_button.isEnabled() and not dialog.profile_actions.isEnabled()
        with pytest.raises(ValueError, match="Wait"):
            dialog.apply_library_profile(profile("printer"))
        assert dialog.value() == before
    finally:
        dialog.worker = None
        dialog.reject()


def test_loading_full_setup_and_printer_only_retains_correct_scope(qt_application):
    dialog = MediaDialog(None)
    try:
        full = profile()
        full["settings"].update(assignments={"1": "LH_B"}, fallback_stock="LH_C", duplex=True)
        dialog.apply_library_profile(full)
        assert dialog.value()["assignments"] == {"1": "LH_B"}
        assert dialog.value()["duplex"] and dialog.checked is None and dialog.options is None
        before = dialog.value()
        printer = profile("printer", "i300")
        printer["settings"]["profile_name"] = "Other environment"
        dialog.apply_library_profile(printer)
        assert dialog.value()["printer_profile"]["family"] == "i300"
        for key in ("stocks", "assignments", "fallback_stock", "duplex"):
            assert dialog.value()[key] == before[key]
        assert dialog.tabs.currentIndex() == 2
    finally:
        dialog.reject()


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_library_narrow_layout_scrolls_details_and_keeps_actions_visible(qt_application, tmp_path, theme):
    palette, style = qt_application.palette(), qt_application.styleSheet()
    apply_theme(qt_application, theme)
    qt_application.setStyleSheet(global_style())
    source = write(tmp_path / "media.json", profile())
    library = tmp_path / "library"
    import_profiles(library, [source])
    dialog = ProfileLibraryDialog(library)
    try:
        dialog.resize(760, 520)
        dialog.show()
        wait_until(lambda: dialog.worker is None)
        qt_application.processEvents()
        assert dialog.width() <= 760 and dialog.height() <= 520
        for widget in (dialog.import_files, dialog.import_folder, dialog.use_button):
            assert widget.isVisible()
            assert widget.mapTo(dialog, widget.rect().bottomRight()).y() < dialog.height()
        assert dialog.details.toPlainText() and dialog.use_button.isEnabled()
        assert dialog.profiles.currentItem().data(Qt.ItemDataRole.UserRole)["profile"]["kind"] == "media"
    finally:
        dialog.reject()
        qt_application.setStyleSheet(style)
        qt_application.setPalette(palette)
