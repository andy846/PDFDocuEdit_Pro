from __future__ import annotations

import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pytest_configure(config) -> None:
    """Redirect Qt QSettings to a sandbox-safe temporary directory.

    The application uses QSettings() with the native format, which on macOS
    writes under the user's Library/Preferences. Tests run in sandboxes or CI
    containers where that location is not writable, so all settings reads and
    writes are redirected to an INI file under the system temp directory.
    """
    del config  # unused
    from PyQt6.QtCore import QSettings

    settings_dir = tempfile.mkdtemp(prefix="pdfdocuedit-qsettings-")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, settings_dir)
