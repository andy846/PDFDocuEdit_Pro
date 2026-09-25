"""Safe Qt-only resize handles for Windows frameless application windows."""

from __future__ import annotations

import sys

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtWidgets import QWidget


def request_system_rounded_corners(window: QWidget) -> bool:
    """Ask Windows 11 to round a top-level window without altering its frame."""
    if sys.platform != "win32" or sys.getwindowsversion().build < 22000:
        return False

    try:
        import ctypes

        hwnd = int(window.winId())
        if not hwnd:
            return False
        # DWM can round the frame while suppressing its one-pixel border.
        preference = ctypes.c_int(2)  # DWMWCP_ROUND
        no_border = ctypes.c_uint(0xFFFFFFFE)  # DWMWA_COLOR_NONE
        set_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
        set_attribute.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint)
        set_attribute.restype = ctypes.c_long
        handle = ctypes.c_void_p(hwnd)
        rounded = set_attribute(handle, 33, ctypes.byref(preference), ctypes.sizeof(preference))
        borderless = set_attribute(handle, 34, ctypes.byref(no_border), ctypes.sizeof(no_border))
        return rounded == 0 and borderless == 0
    except (AttributeError, OSError, RuntimeError, ValueError):
        return False


class _ResizeHandle(QWidget):
    def __init__(self, parent: QWidget, edges, cursor) -> None:
        super().__init__(parent)
        self._edges = edges
        self.setCursor(cursor)
        self.setStyleSheet("background: transparent;")
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            window = self.window()
            handle = window.windowHandle() if window is not None else None
            if handle is not None and handle.startSystemResize(self._edges):
                event.accept()
                return
        super().mousePressEvent(event)


class FramelessResizeHandles:
    """Eight transparent edge widgets backed by QWindow.startSystemResize()."""

    def __init__(self, window: QWidget, thickness: int = 6, corner: int = 12) -> None:
        self.window = window
        self.thickness = thickness
        self.corner = corner
        edge = Qt.Edge
        cursor = Qt.CursorShape
        self.handles = {
            "top": _ResizeHandle(window, edge.TopEdge, cursor.SizeVerCursor),
            "bottom": _ResizeHandle(window, edge.BottomEdge, cursor.SizeVerCursor),
            "left": _ResizeHandle(window, edge.LeftEdge, cursor.SizeHorCursor),
            "right": _ResizeHandle(window, edge.RightEdge, cursor.SizeHorCursor),
            "top_left": _ResizeHandle(
                window, edge.TopEdge | edge.LeftEdge, cursor.SizeFDiagCursor
            ),
            "top_right": _ResizeHandle(
                window, edge.TopEdge | edge.RightEdge, cursor.SizeBDiagCursor
            ),
            "bottom_left": _ResizeHandle(
                window, edge.BottomEdge | edge.LeftEdge, cursor.SizeBDiagCursor
            ),
            "bottom_right": _ResizeHandle(
                window, edge.BottomEdge | edge.RightEdge, cursor.SizeFDiagCursor
            ),
        }

    def update(self) -> None:
        if self.window.isMaximized() or self.window.isFullScreen():
            for handle in self.handles.values():
                handle.hide()
            return
        width, height = self.window.width(), self.window.height()
        thickness, corner = self.thickness, self.corner
        geometries = {
            "top": QRect(corner, 0, max(0, width - 2 * corner), thickness),
            "bottom": QRect(
                corner,
                max(0, height - thickness),
                max(0, width - 2 * corner),
                thickness,
            ),
            "left": QRect(0, corner, thickness, max(0, height - 2 * corner)),
            "right": QRect(
                max(0, width - thickness),
                corner,
                thickness,
                max(0, height - 2 * corner),
            ),
            "top_left": QRect(0, 0, corner, corner),
            "top_right": QRect(max(0, width - corner), 0, corner, corner),
            "bottom_left": QRect(0, max(0, height - corner), corner, corner),
            "bottom_right": QRect(
                max(0, width - corner),
                max(0, height - corner),
                corner,
                corner,
            ),
        }
        for name, handle in self.handles.items():
            handle.setGeometry(geometries[name])
            handle.show()
            handle.raise_()
