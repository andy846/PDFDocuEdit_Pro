"""Per-document session: engine, undo, canvas, navigation and split view."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QSignalBlocker, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QToolButton,
    QVBoxLayout,
)

from core.pdf_engine import PdfEngine
from core.undo import UndoStack

from .analysis_panel import AnalysisPanel
from .nav_panel import NavPanel
from .pdf_canvas import PdfCanvas


class SplitPane(QFrame):
    """Secondary canvas with an explicit document selector and mode badge."""

    sourceActivated = pyqtSignal(object)
    openRequested = pyqtSignal()
    closeRequested = pyqtSignal()

    def __init__(self, canvas: PdfCanvas, parent=None):
        super().__init__(parent)
        self.setObjectName("splitPane")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("splitPaneHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 4, 6, 4)
        header_layout.setSpacing(6)
        label = QLabel("Compare")
        label.setObjectName("splitPaneLabel")
        header_layout.addWidget(label)
        self.source_selector = QComboBox()
        self.source_selector.setObjectName("splitDocumentSelector")
        self.source_selector.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.source_selector.setMinimumContentsLength(18)
        self.source_selector.setToolTip(
            "Choose the document displayed in the comparison pane"
        )
        self.source_selector.activated.connect(self._source_activated)
        header_layout.addWidget(self.source_selector, 1)
        self.mode_badge = QLabel("Same document")
        self.mode_badge.setObjectName("splitModeBadge")
        header_layout.addWidget(self.mode_badge)
        self.open_button = QToolButton()
        self.open_button.setObjectName("splitPaneButton")
        self.open_button.setText("Open PDF…")
        self.open_button.setToolTip("Open another PDF in this comparison pane")
        self.open_button.clicked.connect(self.openRequested.emit)
        header_layout.addWidget(self.open_button)
        self.close_button = QToolButton()
        self.close_button.setObjectName("splitPaneButton")
        self.close_button.setText("×")
        self.close_button.setToolTip("Close split view")
        self.close_button.setAccessibleName("Close split view")
        self.close_button.clicked.connect(self.closeRequested.emit)
        header_layout.addWidget(self.close_button)
        layout.addWidget(header)
        layout.addWidget(canvas, 1)

    def _source_activated(self, index: int) -> None:
        self.sourceActivated.emit(self.source_selector.itemData(index))

    def set_sources(
        self,
        sources: list[tuple[str, object | None]],
        selected: object | None,
    ) -> None:
        blocker = QSignalBlocker(self.source_selector)
        self.source_selector.clear()
        selected_index = 0
        for index, (label, source) in enumerate(sources):
            self.source_selector.addItem(label, source)
            if source is selected:
                selected_index = index
        self.source_selector.setCurrentIndex(selected_index)
        del blocker

    def set_external(self, external: bool) -> None:
        self.setProperty("externalDocument", bool(external))
        self.mode_badge.setText("Read-only comparison" if external else "Same document")
        self.style().unpolish(self)
        self.style().polish(self)


class DocumentSession(QObject):
    """Everything the viewer holds per open document tab."""

    splitSourceRequested = pyqtSignal(object)
    splitOpenRequested = pyqtSignal()
    splitCloseRequested = pyqtSignal()

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
        self.split_source_session: DocumentSession | None = None

        self.canvas = PdfCanvas()
        self.split_canvas: PdfCanvas | None = None
        self.split_pane: SplitPane | None = None
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
            self.split_pane = SplitPane(self.split_canvas)
            self.split_pane.sourceActivated.connect(self.splitSourceRequested.emit)
            self.split_pane.openRequested.connect(self.splitOpenRequested.emit)
            self.split_pane.closeRequested.connect(self.splitCloseRequested.emit)
            self.canvas_area.addWidget(self.split_pane)
            self.set_split_orientation(self.split_orientation)
            self.canvas_area.setStretchFactor(0, 1)
            self.canvas_area.setStretchFactor(1, 1)
            self.set_split_source(None)
            self.reset_split_sizes()
        elif not enabled and self.split_canvas is not None:
            canvas = self.split_canvas
            pane = self.split_pane
            self.split_canvas = None
            self.split_pane = None
            self.split_source_session = None
            canvas.clear()
            if pane is not None:
                pane.setParent(None)
                pane.deleteLater()
            else:
                canvas.setParent(None)
                canvas.deleteLater()

    def set_split_source(self, source: DocumentSession | None) -> bool:
        """Display this document or another open session in the second pane."""

        if source is self:
            source = None
        if source is not None and not source.engine.is_loaded():
            return False
        canvas = self.split_canvas
        if canvas is None:
            return False
        document = self.engine.document if source is None else source.engine.document
        if document is None:
            return False
        canvas.clear()
        self.split_source_session = source
        external = source is not None
        canvas.set_annotations_editable(not external)
        reference = self if source is None else source
        canvas.load_doc(document, reference.canvas.zoom_ratio)
        canvas.set_layout_mode(reference.canvas.layout_mode, emit=False)
        canvas.set_page(reference.canvas.current_page, emit=False)
        if self.split_pane is not None:
            self.split_pane.set_external(external)
        return True

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
