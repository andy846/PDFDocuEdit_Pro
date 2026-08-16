"""Per-document session: engine, undo, canvas, navigation and split view."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QSplitter

from core.pdf_engine import PdfEngine
from core.undo import UndoStack

from .nav_panel import NavPanel
from .pdf_canvas import PdfCanvas


class DocumentSession(QObject):
    """Everything the viewer holds per open document tab."""

    def __init__(self, animations_enabled: bool = True, parent=None):
        super().__init__(parent)
        self.engine = PdfEngine()
        self.undo_stack = UndoStack(self)
        self.display_path: Path | None = None
        self.page = 0

        self.canvas = PdfCanvas()
        self.split_canvas: PdfCanvas | None = None
        self.nav_panel = NavPanel(animations_enabled=animations_enabled)

        self.canvas_area = QSplitter(Qt.Orientation.Horizontal)
        self.canvas_area.addWidget(self.canvas)

        self.tab_widget = QSplitter(Qt.Orientation.Horizontal)
        self.nav_panel.hide()
        self.tab_widget.addWidget(self.nav_panel)
        self.tab_widget.addWidget(self.canvas_area)
        self.tab_widget.setStretchFactor(0, 0)
        self.tab_widget.setStretchFactor(1, 1)
        self.tab_widget.setCollapsible(1, False)

    # --- split view ------------------------------------------------------
    def set_split(self, enabled: bool) -> None:
        if enabled and self.split_canvas is None:
            self.split_canvas = PdfCanvas()
            self.canvas_area.addWidget(self.split_canvas)
            self.canvas_area.setStretchFactor(0, 1)
            self.canvas_area.setStretchFactor(1, 1)
            if self.engine.document is not None:
                self.split_canvas.load_doc(
                    self.engine.document, self.canvas.zoom_ratio
                )
                self.split_canvas.set_page(self.page, emit=False)
        elif not enabled and self.split_canvas is not None:
            canvas = self.split_canvas
            self.split_canvas = None
            canvas.clear()
            canvas.setParent(None)
            canvas.deleteLater()

    @property
    def has_split(self) -> bool:
        return self.split_canvas is not None

    # --- chrome ----------------------------------------------------------
    @property
    def document_name(self) -> str:
        return self.display_path.name if self.display_path else "Untitled"

    @property
    def tab_title(self) -> str:
        suffix = " *" if self.engine.is_modified else ""
        return f"{self.document_name}{suffix}"

    def set_animations_enabled(self, enabled: bool) -> None:
        self.nav_panel.set_animations_enabled(enabled)

    def refresh_icons(self) -> None:
        self.canvas.update_theme()
        self.nav_panel.refresh_icons()
        if self.split_canvas is not None:
            self.split_canvas.update_theme()

    def close(self) -> None:
        """Quiesce background renders and release the document."""
        self.canvas.wait_for_renders()
        if self.split_canvas is not None:
            self.split_canvas.wait_for_renders()
        self.engine.close()
