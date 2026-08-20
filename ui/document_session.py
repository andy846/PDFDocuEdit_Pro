"""Per-document session: engine, undo, canvas, navigation and split view."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QSplitter

from core.pdf_engine import PdfEngine
from core.undo import UndoStack

from .analysis_panel import AnalysisPanel
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
        self.split_orientation = "horizontal"
        self.split_sync_page = False
        self.split_sync_zoom = False
        self._split_syncing = False

        self.canvas = PdfCanvas()
        self.split_canvas: PdfCanvas | None = None
        self.nav_panel = NavPanel(animations_enabled=animations_enabled)
        self.search_panel = self.nav_panel.search
        self.search_panel.hide()
        self.analysis_panel = AnalysisPanel()
        self.analysis_panel.hide()

        self.canvas_area = QSplitter(Qt.Orientation.Horizontal)
        self.canvas_area.addWidget(self.canvas)
        self.canvas.pageChanged.connect(self._sync_page_from_primary)
        self.canvas.zoomChanged.connect(self._sync_zoom_from_primary)

        self.tab_widget = QSplitter(Qt.Orientation.Horizontal)
        self.nav_panel.hide()
        self.tab_widget.addWidget(self.nav_panel)
        self.tab_widget.addWidget(self.canvas_area)
        self.tab_widget.addWidget(self.search_panel)
        self.tab_widget.addWidget(self.analysis_panel)
        self.tab_widget.setStretchFactor(0, 0)
        self.tab_widget.setStretchFactor(1, 1)
        self.tab_widget.setStretchFactor(2, 0)
        self.tab_widget.setStretchFactor(3, 0)
        self.tab_widget.setCollapsible(1, False)

    # --- split view ------------------------------------------------------
    def set_split(self, enabled: bool) -> None:
        if enabled and self.split_canvas is None:
            self.split_canvas = PdfCanvas()
            self.split_canvas.pageChanged.connect(self._sync_page_from_secondary)
            self.split_canvas.zoomChanged.connect(self._sync_zoom_from_secondary)
            self.canvas_area.addWidget(self.split_canvas)
            self.set_split_orientation(self.split_orientation)
            self.canvas_area.setStretchFactor(0, 1)
            self.canvas_area.setStretchFactor(1, 1)
            if self.engine.document is not None:
                self.split_canvas.load_doc(
                    self.engine.document, self.canvas.zoom_ratio
                )
                self.split_canvas.set_page(self.page, emit=False)
            self.reset_split_sizes()
        elif not enabled and self.split_canvas is not None:
            canvas = self.split_canvas
            self.split_canvas = None
            canvas.clear()
            canvas.setParent(None)
            canvas.deleteLater()

    def set_split_orientation(self, orientation: str) -> None:
        self.split_orientation = (
            "vertical" if orientation == "vertical" else "horizontal"
        )
        qt_orientation = (
            Qt.Orientation.Vertical
            if self.split_orientation == "vertical"
            else Qt.Orientation.Horizontal
        )
        self.canvas_area.setOrientation(qt_orientation)
        if self.split_canvas is not None:
            self.reset_split_sizes()

    def set_split_sync(
        self,
        *,
        page: bool | None = None,
        zoom: bool | None = None,
    ) -> None:
        if page is not None:
            self.split_sync_page = bool(page)
            if self.split_sync_page and self.split_canvas is not None:
                self.split_canvas.set_page(self.canvas.current_page, emit=False)
        if zoom is not None:
            self.split_sync_zoom = bool(zoom)
            if self.split_sync_zoom and self.split_canvas is not None:
                self.split_canvas.set_zoom(self.canvas.zoom_ratio, emit=False)

    def reset_split_sizes(self) -> None:
        if self.split_canvas is None:
            return
        extent = (
            self.canvas_area.height()
            if self.canvas_area.orientation() == Qt.Orientation.Vertical
            else self.canvas_area.width()
        )
        half = max(1, extent // 2)
        self.canvas_area.setSizes([half, half])

    def _sync_page_from_primary(self, page: int) -> None:
        if (
            self._split_syncing
            or not self.split_sync_page
            or self.split_canvas is None
        ):
            return
        self._split_syncing = True
        try:
            self.split_canvas.set_page(page, emit=False)
        finally:
            self._split_syncing = False

    def _sync_page_from_secondary(self, page: int) -> None:
        if self._split_syncing or not self.split_sync_page:
            return
        self._split_syncing = True
        try:
            self.canvas.set_page(page)
        finally:
            self._split_syncing = False

    def _sync_zoom_from_primary(self, ratio: float) -> None:
        if (
            self._split_syncing
            or not self.split_sync_zoom
            or self.split_canvas is None
        ):
            return
        self._split_syncing = True
        try:
            self.split_canvas.set_zoom(ratio, emit=False)
        finally:
            self._split_syncing = False

    def _sync_zoom_from_secondary(self, ratio: float) -> None:
        if self._split_syncing or not self.split_sync_zoom:
            return
        self._split_syncing = True
        try:
            self.canvas.set_zoom(ratio)
        finally:
            self._split_syncing = False

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
        self.canvas.clear()
        if self.split_canvas is not None:
            self.split_canvas.clear()
        self.nav_panel.clear_document()
        self.analysis_panel.hide()
        self.engine.close()
