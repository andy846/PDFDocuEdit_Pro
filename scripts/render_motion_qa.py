"""Render deterministic Light and Dark screenshots for main-window visual QA."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import fitz
from PyQt6.QtCore import QEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.viewer as viewer_module  # noqa: E402
from core.settings import SettingsManager  # noqa: E402


def _make_pdf(path: Path) -> None:
    with fitz.open() as document:
        for index in range(2):
            page = document.new_page(width=595, height=842)
            page.insert_text((72, 92), f"PDFDocuEdit Pro visual QA — page {index + 1}", fontsize=18)
            page.insert_text((72, 132), "Motion, contrast, context options and canvas depth.")
        document.save(path)


def main() -> int:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "/private/tmp")
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(["pdfdocuedit-visual-qa"])
    with tempfile.TemporaryDirectory(prefix="pdfdocuedit-visual-") as value:
        temporary = Path(value)
        viewer_module.SettingsManager = lambda: SettingsManager(temporary / "settings.json")
        window = viewer_module.PDFViewer()
        window.resize(1440, 900)
        window.show()
        window._apply_theme("light")
        QTest.qWait(220)

        hover_button = window.side_panel._buttons["office_to_pdf"]
        app.sendEvent(hover_button, QEvent(QEvent.Type.Enter))
        window.info_bar.show_message(
            "Interactive workspace ready — hover states and motion are enabled.",
            "success",
            0,
        )
        QTest.qWait(240)
        window.grab().save(str(output / "pdfdocuedit-motion-light.png"))

        app.sendEvent(hover_button, QEvent(QEvent.Type.Leave))
        source = temporary / "visual-qa.pdf"
        _make_pdf(source)
        window.load_file(str(source))
        window._apply_theme("dark")
        window._show_context("rotate")
        QTest.qWait(260)
        window.info_bar.show_message("Rotate options opened in the live context panel.", "info", 0)
        QTest.qWait(220)
        window.grab().save(str(output / "pdfdocuedit-motion-dark-context.png"))
        window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
