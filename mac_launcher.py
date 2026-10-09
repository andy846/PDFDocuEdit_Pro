"""Fixed Mac application shell; updates live outside its signed bundle."""
from __future__ import annotations

import json
import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path


def main():
    from PyQt6.QtCore import QEvent, QObject, QTimer, pyqtSignal
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from launcher import supervise
    from updates.macos import installation_for, register_shell
    from updates.runtime import FileLock, queue_launch
    from updates.target import UpdateTarget
    resources = Path(sys.executable).resolve().parent.parent / "Resources"
    settings = json.loads((resources / "bootstrap.json").read_text(encoding="utf-8"))
    target = UpdateTarget(**settings["target"])
    installation = installation_for(resources / "Initial.app", settings["version"], target)
    register_shell(installation, sys.executable)
    root = installation.root
    handler = RotatingFileHandler(root / "logs/updater.log", maxBytes=1024 * 1024, backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")

    class Shell(QApplication):
        def event(self, event):
            if event.type() == QEvent.Type.FileOpen:
                queue_launch(root, [event.file()] if event.file() else [])
                return True
            if event.type() == QEvent.Type.ApplicationActivate:
                queue_launch(root, [])
            return super().event(event)

    app = Shell([])
    app.setQuitOnLastWindowClosed(False)
    lock = FileLock(root / "launcher.lock")
    paths = [str(Path(arg).resolve()) for arg in sys.argv[1:] if Path(arg).is_file()]
    if not lock.acquire():
        queue_launch(root, paths)
        return 0

    class Completion(QObject):
        ended = pyqtSignal(int)
        failed = pyqtSignal(str)

    signals = Completion()
    signals.ended.connect(app.exit)
    def failed(text):
        QMessageBox.critical(None, "PDFDocuEdit Pro update", text)
        app.exit(1)
    signals.failed.connect(failed)

    def run():
        try:
            with FileLock(root / "app.lock"):
                if installation.recover():
                    logging.warning("Recovered an interrupted update.")
            result = supervise(installation, paths)
        except Exception:
            logging.exception("Mac launcher failed")
            signals.failed.emit("The application could not start. Your documents were not modified.")
            return
        signals.ended.emit(result)

    thread = threading.Thread(target=run, daemon=False)
    QTimer.singleShot(0, thread.start)
    try:
        result = app.exec()
        thread.join()
        return result
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
