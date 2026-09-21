"""Stable Windows taskbar identity and managed-launcher pinning metadata."""
from __future__ import annotations

import ctypes
import logging
import subprocess
import sys
from pathlib import Path
from uuid import UUID

APP_USER_MODEL_ID = "AndyLeung.PDFDocuEditPro"
_PROPERTY_SET = "9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3"
_STORE_IID = "886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"


class _GUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ubyte * 16)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(UUID(value).bytes_le)


class _PropertyKey(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_uint32)]


def _check(result):
    if result < 0:
        raise OSError(f"Windows shell HRESULT 0x{result & 0xffffffff:08x}")


class _WindowStore:
    """Small IPropertyStore wrapper, with deterministic COM/variant cleanup."""
    def __init__(self, hwnd):
        shell = ctypes.WinDLL("shell32")
        get_store = shell.SHGetPropertyStoreForWindow
        get_store.argtypes = [ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
        get_store.restype = ctypes.c_long
        self.pointer = ctypes.c_void_p()
        _check(get_store(hwnd, ctypes.byref(_GUID.parse(_STORE_IID)), ctypes.byref(self.pointer)))
        self.vtable = ctypes.cast(self.pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        self.clear = ctypes.WinDLL("ole32").PropVariantClear
        self.clear.argtypes = [ctypes.c_void_p]
        self.clear.restype = ctypes.c_long

    def _variant(self):
        # PROPVARIANT has an eight-byte header and an architecture-sized union.
        return ctypes.create_string_buffer(24 if ctypes.sizeof(ctypes.c_void_p) == 8 else 16)

    def set(self, pid, text):
        value = self._variant()
        key = _PropertyKey(_GUID.parse(_PROPERTY_SET), pid)
        # SetValue copies the string. Keep Python-owned storage alive until
        # it returns; only GetValue variants require PropVariantClear.
        text_buffer = ctypes.create_unicode_buffer(text) if text is not None else None
        if text_buffer is not None:
            ctypes.c_ushort.from_buffer(value).value = 31  # VT_LPWSTR
            ctypes.c_void_p.from_buffer(value, 8).value = ctypes.addressof(text_buffer)
        method = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                   ctypes.POINTER(_PropertyKey), ctypes.c_void_p)(self.vtable[6])
        _check(method(self.pointer, ctypes.byref(key), value))

    def get(self, pid):
        value = self._variant()
        key = _PropertyKey(_GUID.parse(_PROPERTY_SET), pid)
        try:
            method = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                       ctypes.POINTER(_PropertyKey), ctypes.c_void_p)(self.vtable[5])
            _check(method(self.pointer, ctypes.byref(key), value))
            if ctypes.c_ushort.from_buffer(value).value == 31:  # VT_LPWSTR
                return ctypes.wstring_at(ctypes.c_void_p.from_buffer(value, 8).value)
            return None
        finally:
            self.clear(value)

    def close(self):
        if self.pointer:
            release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(self.vtable[2])
            release(self.pointer)
            self.pointer = ctypes.c_void_p()


def set_process_identity():
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        function = ctypes.WinDLL("shell32").SetCurrentProcessExplicitAppUserModelID
        function.argtypes = [ctypes.c_wchar_p]
        function.restype = ctypes.c_long
        _check(function(APP_USER_MODEL_ID))
    except Exception:
        logging.getLogger(__name__).exception("Cannot set Windows application identity")


def relaunch_properties(root: Path):
    launcher = root / "Launcher.exe"
    # Relaunch properties must precede ID: setting ID refreshes taskbar metadata.
    return {2: subprocess.list2cmdline([str(launcher)]),
            4: "PDFDocuEdit Pro", 3: f"{launcher},0", 5: APP_USER_MODEL_ID}


def configure_managed_window(hwnd: int, root: Path):
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    store = None
    try:
        store = _WindowStore(hwnd)
        for pid, text in relaunch_properties(root).items():
            store.set(pid, text)
    except Exception:
        logging.getLogger(__name__).exception("Cannot configure managed taskbar pinning")
    finally:
        if store is not None:
            store.close()


def clear_managed_window(hwnd: int):
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    store = None
    try:
        store = _WindowStore(hwnd)
        for pid in (2, 4, 3, 5):
            store.set(pid, None)
    except Exception:
        logging.getLogger(__name__).debug("Window properties already unavailable", exc_info=True)
    finally:
        if store is not None:
            store.close()
