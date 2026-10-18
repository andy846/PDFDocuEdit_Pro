"""Shared bounded-output settings, drafts and narrow layout."""

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_recommended_policy_preview_and_invalid_draft(app):
    from composition.designer.output_limits import OutputLimitsPanel

    panel = OutputLimitsPanel()
    assert panel.policy()["pdf_bytes"] == 250_000_000
    assert panel.policy()["ps_bytes"] == 500_000_000
    assert "1000SHT_1000ENV_S" in panel.preview.text()
    panel.mode.setCurrentIndex(panel.mode.findData("custom"))
    panel.pattern.setText("missing_number")
    with pytest.raises(ValueError):
        panel.policy()
    panel.mode.setCurrentIndex(panel.mode.findData("summary"))
    assert panel.pattern.text() == "missing_number"
    panel.mode.setCurrentIndex(panel.mode.findData("custom"))
    assert "part.number" in panel.error.text()


def test_policy_roundtrip_and_narrow_controls(app):
    from composition.designer.output_limits import OutputLimitsPanel

    panel = OutputLimitsPanel()
    value = panel.policy()
    value["envelopes"] = 20
    panel.set_policy(value)
    assert panel.policy() == value
    panel.resize(360, 220)
    panel.show()
    app.processEvents()
    assert panel.scroll.horizontalScrollBar().maximum() == 0
    panel.close()


def test_unresolvable_custom_name_cannot_apply(app):
    from PyQt6.QtCore import QSettings, QTimer
    from PyQt6.QtWidgets import QDialogButtonBox

    from composition.designer.output_limits import OutputLimitsControl, OutputLimitsPanel

    control = OutputLimitsControl(
        preferences=QSettings(
            QSettings.Format.IniFormat, QSettings.Scope.UserScope, "BoundedOutputTest", "NoPersist"
        )
    )
    observed = []

    def inspect():
        dialog = app.activeModalWidget()
        try:
            panel = dialog.findChild(OutputLimitsPanel)
            panel.mode.setCurrentIndex(panel.mode.findData("custom"))
            panel.pattern.setText("{{job.missing}}_part{{part.number}}")
            box = dialog.findChild(QDialogButtonBox)
            observed.append(box.button(QDialogButtonBox.StandardButton.Ok).isEnabled())
        finally:
            dialog.reject()

    QTimer.singleShot(20, inspect)
    control.configure()
    assert observed == [False]


def test_keyboard_cancel_preserves_policy_and_dialog_fits_screen(app):
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtTest import QTest

    from composition.designer.output_limits import OutputLimitsControl, OutputLimitsPanel

    control = OutputLimitsControl()
    before = control.policy()
    observed = []

    def interact():
        dialog = app.activeModalWidget()
        panel = dialog.findChild(OutputLimitsPanel)
        available = dialog.screen().availableGeometry()
        observed.append(dialog.width() <= available.width() and dialog.height() <= available.height())
        panel.pdf.setValue(123)
        panel.pdf.setFocus()
        QTest.keyClick(panel.pdf, Qt.Key.Key_Tab)
        observed.append(app.focusWidget() is not None)
        QTest.keyClick(dialog, Qt.Key.Key_Escape)

    QTimer.singleShot(20, interact)
    control.configure()
    assert observed == [True, True]
    assert control.policy() == before
