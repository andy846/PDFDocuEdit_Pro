"""Right-hand contextual page-operation and annotation panel."""

from __future__ import annotations

import fitz
from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, pyqtProperty, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.annotations import STAMP_IDS, list_annotations
from core.pdf_engine import parse_page_range
from styles.tokens import D, S

from .motion import MotionIconButton

SWATCHES: dict[str, str] = {
    "yellow": "#ffd54a",
    "green": "#81c784",
    "cyan": "#4dd0e1",
    "pink": "#f48fb1",
    "orange": "#ffb74d",
    "red": "#e57373",
}


class ContextPanel(QFrame):
    closed = pyqtSignal()
    rotateRequested = pyqtSignal(str, int)
    deleteRequested = pyqtSignal(str)
    extractRequested = pyqtSignal(str)
    splitRequested = pyqtSignal(int)
    insertRequested = pyqtSignal(str, str, int)
    orderRequested = pyqtSignal(str)
    annotationColorChanged = pyqtSignal(str)
    annotationWidthChanged = pyqtSignal(int)
    stampKindChanged = pyqtSignal(str)
    imagePathChanged = pyqtSignal(str)
    removeAnnotationRequested = pyqtSignal(int)
    annotateRefreshRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("contextPanel")
        self._panel_width = 0
        self._page_count = 0
        self._animations_enabled = True
        self._closing = False
        self.setMinimumWidth(0)
        self.setMaximumWidth(0)
        self._width_animation = QPropertyAnimation(self, b"panelWidth", self)
        self._width_animation.setDuration(180)
        self._width_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._width_animation.finished.connect(self._animation_finished)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(S.LG, S.MD, S.LG, S.LG)
        layout.setSpacing(S.MD)

        header = QHBoxLayout()
        self._title = QLabel("Options")
        self._title.setObjectName("appTitle")
        header.addWidget(self._title)
        header.addStretch(1)
        self._close = MotionIconButton("x", "Close options", D.ICON_SM)
        self._close.clicked.connect(self.closed.emit)
        header.addWidget(self._close)
        layout.addLayout(header)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack, 1)
        self._pages: dict[str, QWidget] = {}
        self._build_rotate()
        self._build_ranges("delete", "Delete Pages", self.deleteRequested)
        self._build_ranges("extract", "Extract Pages", self.extractRequested)
        self._build_split()
        self._build_insert()
        self._build_order()
        self._build_annotate()

    @pyqtProperty(int)
    def panelWidth(self) -> int:  # noqa: N802 - Qt property naming
        return self._panel_width

    @panelWidth.setter
    def panelWidth(self, value: int) -> None:  # noqa: N802 - Qt property naming
        value = max(0, value)
        self._panel_width = value
        self.setMinimumWidth(value)
        self.setMaximumWidth(value)
        splitter = self.parentWidget()
        if isinstance(splitter, QSplitter):
            sizes = splitter.sizes()
            if len(sizes) >= 3:
                total = sum(sizes)
                left = sizes[0]
                sizes[2] = value
                sizes[1] = max(0, total - left - value)
                splitter.setSizes(sizes)

    def _add_page(self, key: str, page: QWidget) -> None:
        self._pages[key] = page
        self._stack.addWidget(page)

    def _base_page(self, description: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        description_label = QLabel(description)
        description_label.setObjectName("secondary")
        description_label.setWordWrap(True)
        layout.addWidget(description_label)
        return page, layout

    def _build_rotate(self) -> None:
        page, layout = self._base_page("Rotate the current page, a page range, or the whole document.")
        form = QFormLayout()
        pages = QLineEdit()
        pages.setPlaceholderText("Current, all, or 1,3,5-8")
        pages.textChanged.connect(lambda text: self._validate_pages_input(pages, text, allow_empty=True))
        angle = QComboBox()
        angle.addItems(["90° clockwise", "180°", "90° counter-clockwise"])
        angle.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow)
        angle.setToolTip("Rotation angle to apply to selected pages")
        form.addRow("Pages", pages)
        form.addRow("Angle", angle)
        layout.addLayout(form)
        self._add_quick_buttons(layout, pages)
        self._validation_rotate = self._add_validation_label(layout)
        apply = QPushButton("Rotate")
        apply.setProperty("primary", True)
        apply.clicked.connect(lambda: self.rotateRequested.emit(pages.text().strip(), (90, 180, -90)[angle.currentIndex()]))
        layout.addWidget(apply)
        layout.addStretch(1)
        page.pages_edit = pages  # type: ignore[attr-defined]
        self._add_page("rotate", page)

    def _build_ranges(self, key: str, action: str, signal) -> None:
        page, layout = self._base_page(f"{action} using one-based page numbers and ranges.")
        pages = QLineEdit()
        pages.setPlaceholderText("e.g. 1,3,5-8")
        pages.textChanged.connect(lambda text: self._validate_pages_input(pages, text))
        layout.addWidget(QLabel("Pages"))
        layout.addWidget(pages)
        self._add_quick_buttons(layout, pages)
        validation_label = self._add_validation_label(layout)
        apply = QPushButton(action)
        apply.setProperty("primary", True)
        apply.clicked.connect(lambda: signal.emit(pages.text().strip()))
        layout.addWidget(apply)
        layout.addStretch(1)
        page.pages_edit = pages  # type: ignore[attr-defined]
        page.validation_label = validation_label  # type: ignore[attr-defined]
        self._add_page(key, page)

    def _build_split(self) -> None:
        page, layout = self._base_page("Create a new PDF after every selected number of pages.")
        every = QSpinBox()
        every.setRange(1, 9999)
        every.setValue(1)
        layout.addWidget(QLabel("Pages per file"))
        layout.addWidget(every)
        apply = QPushButton("Split PDF")
        apply.setProperty("primary", True)
        apply.clicked.connect(lambda: self.splitRequested.emit(every.value()))
        layout.addWidget(apply)
        layout.addStretch(1)
        self._add_page("split", page)

    def _build_insert(self) -> None:
        page, layout = self._base_page("Insert pages from another PDF into this document.")
        form = QFormLayout()
        source = QLineEdit()
        source.setReadOnly(True)
        browse = QPushButton("Choose PDF…")
        browse.setProperty("secondary", True)
        browse.clicked.connect(lambda: self.insertRequested.emit("browse", source.text(), position.value()))
        position = QSpinBox()
        position.setMinimum(1)
        form.addRow("Source", source)
        form.addRow("", browse)
        form.addRow("Insert before page", position)
        layout.addLayout(form)
        apply = QPushButton("Insert all pages")
        apply.setProperty("primary", True)
        apply.clicked.connect(lambda: self.insertRequested.emit("apply", source.text(), position.value()))
        layout.addWidget(apply)
        layout.addStretch(1)
        page.source_edit = source  # type: ignore[attr-defined]
        page.position_spin = position  # type: ignore[attr-defined]
        self._add_page("insert", page)

    def _build_order(self) -> None:
        page, layout = self._base_page("Reorder all pages. Enter each page exactly once.")
        order = QLineEdit()
        order.setPlaceholderText("e.g. 3,1,2,4")
        layout.addWidget(QLabel("New page order"))
        layout.addWidget(order)
        reverse = QPushButton("Reverse all pages")
        reverse.setProperty("secondary", True)
        reverse.clicked.connect(lambda: self.orderRequested.emit("reverse"))
        apply = QPushButton("Apply order")
        apply.setProperty("primary", True)
        apply.clicked.connect(lambda: self.orderRequested.emit(order.text().strip()))
        layout.addWidget(reverse)
        layout.addWidget(apply)
        layout.addStretch(1)
        self._add_page("sort", page)

    def _build_annotate(self) -> None:
        page, layout = self._base_page(
            "Annotation options for the active canvas tool. Changes apply to new annotations."
        )
        layout.addWidget(QLabel("Color"))
        colors_row = QHBoxLayout()
        colors_row.setSpacing(S.XS)
        self._color_buttons: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for key, hex_value in SWATCHES.items():
            button = QPushButton()
            button.setObjectName("swatchButton")
            button.setCheckable(True)
            button.setFixedSize(28, 28)
            button.setToolTip(key.title())
            button.setAccessibleName(f"Annotation color {key}")
            button.setStyleSheet(
                f"QPushButton#swatchButton {{ background: {hex_value};"
                f" border: 2px solid transparent; border-radius: 14px; }}"
                f"QPushButton#swatchButton:checked {{ border: 2px solid #555; }}"
            )
            button.clicked.connect(
                lambda _checked=False, value=key: self.annotationColorChanged.emit(value)
            )
            group.addButton(button)
            colors_row.addWidget(button)
            self._color_buttons[key] = button
        colors_row.addStretch(1)
        layout.addLayout(colors_row)
        self._color_buttons["yellow"].setChecked(True)

        width_row = QHBoxLayout()
        width_row.addWidget(QLabel("Line width"))
        self._annot_width = QSpinBox()
        self._annot_width.setRange(1, 6)
        self._annot_width.setValue(2)
        self._annot_width.valueChanged.connect(self.annotationWidthChanged.emit)
        width_row.addWidget(self._annot_width)
        width_row.addStretch(1)
        layout.addLayout(width_row)

        stamp_form = QFormLayout()
        self._stamp_kind = QComboBox()
        self._stamp_kind.addItems(list(STAMP_IDS.keys()))
        self._stamp_kind.setCurrentText("Draft")
        self._stamp_kind.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow
        )
        self._stamp_kind.currentTextChanged.connect(self.stampKindChanged.emit)
        stamp_form.addRow("Stamp", self._stamp_kind)
        layout.addLayout(stamp_form)

        layout.addWidget(QLabel("Signature / Image source"))
        image_row = QHBoxLayout()
        self._image_edit = QLineEdit()
        self._image_edit.setReadOnly(True)
        self._image_edit.setPlaceholderText("Choose a PNG or JPG")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_image)
        image_row.addWidget(self._image_edit, 1)
        image_row.addWidget(browse)
        layout.addLayout(image_row)

        layout.addWidget(QLabel("Annotations on this page"))
        self._annot_list = QListWidget()
        self._annot_list.setObjectName("navList")
        layout.addWidget(self._annot_list, 1)
        actions = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.setProperty("secondary", True)
        refresh.clicked.connect(self.annotateRefreshRequested.emit)
        remove = QPushButton("Remove Selected")
        remove.setProperty("secondary", True)
        remove.clicked.connect(self._remove_selected_annotation)
        actions.addWidget(refresh)
        actions.addWidget(remove)
        layout.addLayout(actions)
        self._add_page("annotate", page)

    def _browse_image(self) -> None:
        value, _ = QFileDialog.getOpenFileName(
            self, "Choose image", "", "Images (*.png *.jpg *.jpeg)"
        )
        if value:
            self.set_annotate_image(value)
            self.imagePathChanged.emit(value)

    def set_annotate_image(self, path: str) -> None:
        self._image_edit.setText(path)
        self._image_edit.setToolTip(path)

    def refresh_annotation_list(self, page: fitz.Page | None) -> None:
        self._annot_list.clear()
        if page is None:
            return
        try:
            entries = list_annotations(page)
        except Exception:
            entries = []  # never let a stale page crash the panel
        for entry in entries:
            item = QListWidgetItem(f"{entry['kind']}  ·  page area")
            item.setData(Qt.ItemDataRole.UserRole, entry["index"])
            self._annot_list.addItem(item)

    def _remove_selected_annotation(self) -> None:
        item = self._annot_list.currentItem()
        if item is not None:
            index = item.data(Qt.ItemDataRole.UserRole)
            if index is not None:
                self.removeAnnotationRequested.emit(int(index))

    def _add_validation_label(self, layout: QVBoxLayout) -> QLabel:
        label = QLabel()
        label.setObjectName("validationError")
        label.setWordWrap(True)
        label.hide()
        layout.addWidget(label)
        return label

    def _add_quick_buttons(self, layout: QVBoxLayout, pages: QLineEdit) -> None:
        row = QHBoxLayout()
        row.setSpacing(S.XS)
        for text, value in (("All", "all"), ("Odd", "odd"), ("Even", "even"), ("Current", "current")):
            button = QPushButton(text)
            button.setProperty("secondary", True)
            button.setProperty("compact", True)
            button.setFixedHeight(26)
            button.setToolTip(f"Select {value} pages")
            button.clicked.connect(lambda _checked=False, v=value: pages.setText(v))
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)

    def _validate_pages_input(self, edit: QLineEdit, text: str, *, allow_empty: bool = True) -> None:
        """Validate page range text and show status via the input's style and a sibling label."""
        stripped = text.strip()
        if not stripped:
            edit.setProperty("invalid", False)
            edit.style().unpolish(edit)
            edit.style().polish(edit)
            label = self._find_validation_label(edit)
            if label:
                label.hide()
            return
        if self._page_count <= 0:
            return
        normalized = stripped.casefold()
        try:
            if normalized in {"all", "current"}:
                pages = list(range(self._page_count)) if normalized == "all" else [0]
            elif normalized in {"odd", "even"}:
                start = 1 if normalized == "odd" else 2
                pages = list(range(start - 1, self._page_count, 2))
            else:
                pages = parse_page_range(stripped, self._page_count)
            edit.setProperty("invalid", False)
            label = self._find_validation_label(edit)
            if label:
                label.setText(f"{len(pages)} page{'s' if len(pages) != 1 else ''} selected")
                label.setObjectName("pageRangeStatus")
                label.style().unpolish(label)
                label.style().polish(label)
                label.show()
        except Exception as exc:
            edit.setProperty("invalid", True)
            label = self._find_validation_label(edit)
            if label:
                label.setText(str(exc))
                label.setObjectName("validationError")
                label.style().unpolish(label)
                label.style().polish(label)
                label.show()
        edit.style().unpolish(edit)
        edit.style().polish(edit)

    def _find_validation_label(self, edit: QLineEdit) -> QLabel | None:
        page = edit.parentWidget()
        while page is not None and page not in self._pages.values():
            page = page.parentWidget()
        if page is None:
            return None
        return getattr(page, "validation_label", None) or getattr(self, "_validation_rotate", None)

    def show_tool(self, key: str, title: str) -> bool:
        page = self._pages.get(key)
        if not page:
            return False
        was_visible = self.isVisible() and self._panel_width > 0
        self._title.setText(title)
        self._stack.setCurrentWidget(page)
        self._width_animation.stop()
        self._closing = False
        self.show()
        if not was_visible and self._animations_enabled:
            self.panelWidth = 0
            self._width_animation.setStartValue(0)
            self._width_animation.setEndValue(D.CONTEXT_W)
            self._width_animation.start()
        else:
            self.panelWidth = D.CONTEXT_W
        return True

    def close_animated(self) -> None:
        self._width_animation.stop()
        self._closing = True
        if not self.isVisible() or not self._animations_enabled:
            self.panelWidth = 0
            self.hide()
            return
        self._width_animation.setStartValue(self._panel_width)
        self._width_animation.setEndValue(0)
        self._width_animation.start()

    def _animation_finished(self) -> None:
        if self._closing:
            self.panelWidth = 0
            self.hide()
            self._closing = False
        else:
            self.panelWidth = D.CONTEXT_W

    def set_animations_enabled(self, enabled: bool) -> None:
        self._animations_enabled = enabled
        self._close.set_animations_enabled(enabled)

    def set_page_count(self, count: int) -> None:
        self._page_count = count
        insert = self._pages.get("insert")
        if insert:
            insert.position_spin.setMaximum(max(1, count + 1))  # type: ignore[attr-defined]

    def set_insert_source(self, path: str) -> None:
        insert = self._pages.get("insert")
        if insert:
            insert.source_edit.setText(path)  # type: ignore[attr-defined]

    def refresh_icons(self) -> None:
        self._close.refresh_icon()
