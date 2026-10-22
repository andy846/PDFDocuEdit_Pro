"""Synthetic native process-exit probe; no account or customer data is used."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from threading import Event


def run(folder: Path, route: str) -> None:
    from core.pdf_backend import fitz

    # isort: split
    from PyQt6.QtCore import QCoreApplication, QEvent, QSettings, QThreadPool, QTimer
    from PyQt6.QtWidgets import QApplication

    from core import viewer as viewer_module
    from core.settings import SettingsManager
    from ui.deep_search_dialog import OPEN_CURRENT

    folder.mkdir(parents=True, exist_ok=True)
    inputs = folder / "inputs"
    inputs.mkdir()
    for name, pages in (("a.pdf", 1), ("b.pdf", 3)):
        with fitz.open() as doc:
            for _ in range(pages):
                doc.new_page().insert_text((50, 50), "needle")
            doc.save(inputs / name)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(folder / "settings"))
    app = QApplication([])
    viewer_module.SettingsManager = lambda: SettingsManager(folder / "preferences.json")
    window = viewer_module.PDFViewer()
    window._confirm_discard_changes = lambda: True
    window.show()
    window._load_file_sync(str(inputs / "a.pdf"))
    entered, release = Event(), Event()
    original = fitz.Page.get_text
    def controlled(page, *args, **kwargs):
        if page.parent.name.endswith("b.pdf") and page.number == 0:
            entered.set()
            assert release.wait(8)
        return original(page, *args, **kwargs)
    fitz.Page.get_text = controlled
    window._deep_search()
    dialog = window._deep_search_dialog
    dialog.folder.setText(str(inputs))
    dialog.query.setText("needle")
    dialog._search()
    runtime, temporary = dialog._runtime, dialog._store.path.parent
    stage = "starting"
    timer = QTimer()
    def advance():
        nonlocal stage
        if stage == "starting" and entered.is_set():
            dialog.pause_button.click()
            stage = "pausing"
            release.set()
        elif stage == "pausing" and runtime.paused:
            stage = "closing"
            timer.stop()
            if route == "hidden":
                dialog.hide()
            elif route == "open_current":
                dialog._poll_search()
                dialog.open_option.setCurrentIndex(dialog.open_option.findData(OPEN_CURRENT))
                dialog._open_selected(0)
                assert not dialog.isVisible()
            elif route == "child_and_main":
                dialog.close()
            window.close()
    timer.timeout.connect(advance)
    timer.start(10)
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(lambda: app.exit(99))
    deadline.start(10000)
    try:
        code = app.exec()
        assert code == 0 and stage == "closing", (code, stage)
        assert runtime.cancelled and runtime.finished
        assert not temporary.exists()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        assert QThreadPool.globalInstance().waitForDone(3000)
        (folder / "exit.json").write_text(json.dumps({"route": route, "cancelled": runtime.cancelled,
            "finished": runtime.finished, "temporary_removed": not temporary.exists()}), encoding="utf-8")
    finally:
        release.set()
        runtime.cancel()
        fitz.Page.get_text = original


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    run(Path(sys.argv[1]), sys.argv[2])
