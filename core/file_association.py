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

from core.diagnostics import log_failure

PROG_ID = "PDFDocuEditPro.Document"
ASSOCIATED_EXTENSIONS = (".pdf", ".ps", ".eps")


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def is_installed() -> bool:
    """True when running as the packaged executable (not via python)."""
    return _is_frozen()


def _executable() -> str:
    from updates.runtime import managed_root

    root = managed_root()
    if root is not None:
        return str(root / "Launcher.exe")
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
    return (
        _read_default(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{extension}")
        or _read_default(winreg.HKEY_CLASSES_ROOT, extension)
        or _read_default(winreg.HKEY_LOCAL_MACHINE, rf"Software\Classes\{extension}")
    )


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


def unregister_default_app(
    extensions: tuple[str, ...] = ASSOCIATED_EXTENSIONS,
) -> bool:
    """Remove our per-user registration, preserving UserChoice and other apps.

    Only matching values are removed; shared keys are deleted only if empty.
    Returns False on registry access errors. Missing registrations are harmless.
    """
    if sys.platform != "win32":
        return False
    import winreg

    root = winreg.HKEY_CURRENT_USER

    def remove_value(path: str, name: str, expected: str) -> None:
        try:
            with winreg.OpenKey(root, path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                value, _ = winreg.QueryValueEx(key, name)
                if value == expected:
                    winreg.DeleteValue(key, name)
        except FileNotFoundError:
            log_failure('file_association.remove_value: fallback after failure', 10)
            pass

    def remove_empty_key(path: str) -> None:
        try:
            with winreg.OpenKey(root, path) as key:
                subkeys, values, _ = winreg.QueryInfoKey(key)
            if not subkeys and not values:
                winreg.DeleteKey(root, path)
        except FileNotFoundError:
            log_failure('file_association.remove_empty_key: fallback after failure', 10)
            pass

    try:
        for extension in extensions:
            path = rf"Software\Classes\{extension}"
            remove_value(path, "", PROG_ID)
            remove_value(rf"{path}\OpenWithProgids", PROG_ID, "")
            remove_empty_key(rf"{path}\OpenWithProgids")
            remove_empty_key(path)
        executable = _executable()
        prog = rf"Software\Classes\{PROG_ID}"
        remove_value(rf"{prog}\shell\open\command", "", f'"{executable}" "%1"')
        remove_value(rf"{prog}\DefaultIcon", "", f"{executable},0")
        remove_value(prog, "", "PDFDocuEdit Pro Document")
        for suffix in (r"\shell\open\command", r"\shell\open", r"\shell", r"\DefaultIcon", ""):
            remove_empty_key(prog + suffix)
    except OSError:
        return False
    return True


def open_default_apps_settings() -> None:
    """Open the Windows default-apps settings page."""
    if sys.platform != "win32":
        return
    try:
        import subprocess

        subprocess.Popen(["explorer.exe", "ms-settings:defaultapps"])
    except OSError:
        log_failure('file_association.open_default_apps_settings: fallback after failure', 10)
        pass
