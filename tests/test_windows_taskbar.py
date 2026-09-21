"""Stable launcher identity, including real Windows property-store roundtrip."""
import sys
from pathlib import Path

import pytest

from updates.windows_shell import APP_USER_MODEL_ID, _WindowStore, relaunch_properties


def test_relaunch_targets_stable_launcher_with_quoted_spaces():
    values = relaunch_properties(Path("C:/Portable Apps/PDFDocuEditPro"))
    assert values[2].startswith('"') and values[2].endswith('Launcher.exe"')
    assert "versions" not in values[2]
    assert values[4] == "PDFDocuEdit Pro"
    assert values[3].endswith("Launcher.exe,0")
    assert values[5] == APP_USER_MODEL_ID
    assert list(values)[-1] == 5
    installer = (Path(__file__).resolve().parents[1] / "installer/PDFDocuEditPro.iss").read_text()
    assert f'#define MyAppUserModelId "{APP_USER_MODEL_ID}"' in installer


@pytest.mark.skipif(sys.platform != "win32", reason="Windows shell API")
def test_real_window_property_store_roundtrip():
    # Use a native hidden STATIC window, independent of Qt's offscreen plugin.
    import ctypes
    user32 = ctypes.WinDLL("user32")
    create = user32.CreateWindowExW
    create.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32,
                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                       ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    create.restype = ctypes.c_void_p
    destroy = user32.DestroyWindow
    destroy.argtypes = [ctypes.c_void_p]
    hwnd = create(0, "STATIC", "Taskbar identity test", 0, 0, 0, 10, 10, None, None, None, None)
    assert hwnd
    store = None
    try:
        store = _WindowStore(hwnd)
        values = relaunch_properties(Path("C:/Portable Apps/PDFDocuEditPro"))
        for pid, text in values.items():
            store.set(pid, text)
        for pid, text in values.items():
            assert store.get(pid) == text
        for pid in values:
            store.set(pid, None)
            assert store.get(pid) is None
    finally:
        if store is not None:
            store.close()
        destroy(hwnd)
