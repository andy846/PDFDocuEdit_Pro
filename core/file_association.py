"""Windows default-app (file association) detection and registration.

The registration writes to the per-user classes key (HKCU\\Software\\Classes),
which needs no administrator rights. On Windows 10+ an existing "UserChoice"
entry (set via Explorer's Open-with dialog) is hash-protected and cannot be
overwritten programmatically; callers then guide the user to the Settings
page instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROG_ID = "PDFDocuEditPro.Document"
ASSOCIATED_EXTENSIONS = (".pdf", ".ps", ".eps")


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def is_installed() -> bool:
    """True when running as the packaged executable (not via python)."""
    return _is_frozen()


def _executable() -> str:
    return str(Path(sys.executable).resolve())


def _open_key(root, path: str):
    import winreg

    try:
        return winreg.OpenKey(root, path)
    except OSError:
        return None


def _read_default(root, path: str) -> str | None:
    import winreg

    key = _open_key(root, path)
    if key is None:
        return None
    try:
        value, _kind = winreg.QueryValueEx(key, "")
        return str(value) if value else None
    except OSError:
        return None
    finally:
        winreg.CloseKey(key)


def _user_choice_prog_id(extension: str) -> str | None:
    """The UserChoice ProgId for an extension (Windows 10+)."""
    import winreg

    key = _open_key(
        winreg.HKEY_CURRENT_USER,
        rf"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{extension}\UserChoice",
    )
    if key is None:
        return None
    try:
        value, _kind = winreg.QueryValueEx(key, "ProgId")
        return str(value) if value else None
    except OSError:
        return None
    finally:
        winreg.CloseKey(key)


def default_app_extension(extension: str) -> str | None:
    """The ProgId currently associated with an extension (UserChoice first)."""
    import winreg

    choice = _user_choice_prog_id(extension)
    if choice:
        return choice
    return _read_default(winreg.HKEY_CLASSES_ROOT, extension)


def is_default_app(extensions: tuple[str, ...] = ASSOCIATED_EXTENSIONS) -> bool:
    """True when the app is the default handler for every extension."""
    if sys.platform != "win32" or not _is_frozen():
        return False
    for extension in extensions:
        if default_app_extension(extension) != PROG_ID:
            return False
    return True


def register_default_app(
    extensions: tuple[str, ...] = ASSOCIATED_EXTENSIONS,
) -> bool:
    """Register the per-user association and return whether it now holds.

    Returns False when Windows keeps a protected UserChoice entry; the user
    must then confirm through the Settings UI.
    """
    if sys.platform != "win32":
        return False
    import winreg

    executable = _executable()
    classes = winreg.HKEY_CURRENT_USER
    prog = rf"Software\Classes\{PROG_ID}"
    with winreg.CreateKey(classes, prog) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "PDFDocuEdit Pro Document")
    with winreg.CreateKey(classes, rf"{prog}\DefaultIcon") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f"{executable},0")
    with winreg.CreateKey(classes, rf"{prog}\shell\open\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{executable}" "%1"')
    for extension in extensions:
        with winreg.CreateKey(classes, rf"Software\Classes\{extension}") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, PROG_ID)
    return is_default_app(extensions)


def open_default_apps_settings() -> None:
    """Open the Windows default-apps settings page."""
    if sys.platform != "win32":
        return
    try:
        import subprocess

        subprocess.Popen(["explorer.exe", "ms-settings:defaultapps"])
    except OSError:
        pass
