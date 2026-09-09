"""Qt startup handshake, managed settings import and file-open requests."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from PyQt6.QtCore import QStandardPaths, QTimer
from PyQt6.QtWidgets import QMessageBox

from .protocol import atomic_json, read_json
from .runtime import TOKEN_ENV, managed_root


def import_settings() -> None:
    root = managed_root()
    if root is None or (root / "data" / ".migration-complete").exists():
        return
    original = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    if original:
        source = Path(original) / "settings.json"
        target = root / "data" / "config" / "settings.json"
        if source.is_file() and not target.exists():
            answer = QMessageBox.question(None, "Import Existing Settings", "Copy settings from your existing PDFDocuEdit Pro installation?\nThe original settings and PDF documents will be preserved.")
            if answer == QMessageBox.StandardButton.Yes:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / ".migration-complete").touch()


def activate(viewer, open_paths) -> None:
    root = managed_root()
    if root is None:
        return
    token = os.environ[TOKEN_ENV]
    viewer.setEnabled(False)
    accepted = root / f"accepted-{token}.json"
    timer = QTimer(viewer)
    viewer._update_handshake_timer = timer

    def poll():
        if accepted.exists() and read_json(accepted).get("token") == token:
            viewer.setEnabled(True)
            timer.stop()
            requests.start(300)
            open_paths([])

    def consume():
        for request in sorted((root / "requests").glob("*.json")):
            try:
                payload = read_json(request)
                paths = payload.get("paths", [])
                if isinstance(paths, list) and all(isinstance(p, str) for p in paths):
                    open_paths(paths)
            except (OSError, ValueError):
                pass
            finally:
                request.unlink(missing_ok=True)

    requests = QTimer(viewer)
    viewer._update_requests_timer = requests
    requests.timeout.connect(consume)
    timer.timeout.connect(poll)
    atomic_json(root / f"ready-{token}.json", {"token": token})
    timer.start(100)
