from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qt_application():
    """Keep Qt alive across UI modules; destroying and recreating it is unsafe."""
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    # The real entry point installs the proxy theme before constructing any
    # controls. Mirror that lifecycle instead of replacing native/offscreen
    # styles for the first time after several production dialogs were closed.
    from styles.theme import apply_theme
    apply_theme(app, "system")
    yield app


@pytest.fixture(autouse=True)
def flush_qt_deferred_deletions(request):
    """Retain one application for GUI tests, then flush deferred deletions.

    Some older UI modules construct QApplication inside each test. Use the
    existing CI UI group to acquire the session fixture before any widget is
    created, matching the real entry point. Other modules keep their existing
    explicit application/headless setup; no second GUI test registry is needed.
    """
    from scripts.ci_plan import UI_TESTS
    path = request.node.path.relative_to(Path(__file__).resolve().parent.parent).as_posix()
    if path in UI_TESTS:
        request.getfixturevalue("qt_application")
    yield
    from PyQt6.QtCore import QCoreApplication, QEvent

    if QCoreApplication.instance() is not None:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def pytest_configure(config) -> None:
    """Redirect Qt QSettings to a sandbox-safe temporary directory.

    The application uses QSettings() with the native format, which on macOS
    writes under the user's Library/Preferences. Tests run in sandboxes or CI
    containers where that location is not writable, so all settings reads and
    writes are redirected to an INI file under the system temp directory.
    """
    del config  # unused
    # Match the application entrypoint's native DLL initialization order.
    from core.pdf_backend import fitz  # noqa: F401

    # isort: split
    from PyQt6.QtCore import QSettings

    settings_dir = tempfile.mkdtemp(prefix="pdfdocuedit-qsettings-")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, settings_dir)
