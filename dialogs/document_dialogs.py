"""Detailed document inspection, visual organization, and print options."""

from __future__ import annotations

import uuid
from dataclasses import replace
from pathlib import Path

import fitz
from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QImage, QPainter, QPixmap, QTransform
from PyQt6.QtPrintSupport import QPrinterInfo
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.pdf_engine import PagePlanEntry, parse_page_range

from .base import SortableTableWidget, ToolDialog
from .print_profile import collect_print_profile, quality_changed, restore_print_profile, selected_quality_dpi


def _fitz_pixmap_image(pixmap: fitz.Pixmap) -> QImage:
    format_ = QImage.Format.Format_RGBA8888 if pixmap.alpha else QImage.Format.Format_RGB888
    return QImage(
        pixmap.samples, pixmap.width, pixmap.height, pixmap.stride, format_
    ).copy()


ORGANIZER_CELL_W = 164
ORGANIZER_CELL_H = 228
ORGANIZER_THUMB_W = 132
ORGANIZER_THUMB_H = 176
ORGANIZER_MARGIN = 12
ORGANIZER_SPACING = 8


class OrganizerPageWidget(QWidget):
    """One page card with a stable identity independent of its source page."""

    def __init__(self, entry: PagePlanEntry | int, parent=None):
        super().__init__(parent)
        if isinstance(entry, int):
            entry = PagePlanEntry(uuid.uuid4().hex, "current", entry)
        self.entry = entry
        self.original_index = entry.source_page if entry.source_kind == "current" else -1
        self.rotation_delta = 0
        self.setObjectName("organizerPageWidget")
        self.setProperty("selected", False)
        self.setProperty("lifted", False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(ORGANIZER_CELL_W, ORGANIZER_CELL_H)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 6)
        layout.setSpacing(4)
        self._thumb = QLabel()
        self._thumb.setObjectName("organizerPageThumb")
        self._thumb.setFixedSize(ORGANIZER_THUMB_W, ORGANIZER_THUMB_H)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._thumb, 0, Qt.AlignmentFlag.AlignHCenter)
        self._caption = QLabel(self._label())
        self._caption.setObjectName("organizerPageCaption")
        self._caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._caption)
        self._badge = QLabel("✓", self)
        self._badge.setObjectName("organizerSelectionBadge")
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setFixedSize(24, 24)
        self._badge.move(132, 6)
        self._badge.hide()

    def _label(self) -> str:
        if self.entry.source_kind == "external":
            source = Path(self.entry.source_path).name
            return f"{source} · p{self.entry.source_page + 1}"
        return f"Page {self.entry.source_page + 1}"

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        self._thumb.setPixmap(pixmap)

    def set_rotation(self, rotation: int) -> None:
        self.rotation_delta = int(rotation) % 360
        text = self._label()
        if self.rotation_delta:
            text += f" · {self.rotation_delta}°"
        self._caption.setText(text)

    def rotate(self, amount: int) -> None:
        self.set_rotation(self.rotation_delta + amount)
        self.entry = replace(
            self.entry,
            final_rotation=(self.entry.final_rotation + amount) % 360,
        )

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self._badge.setVisible(selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def set_lifted(self, lifted: bool) -> None:
        self.setProperty("lifted", lifted)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class OrganizerGrid(QScrollArea):
    """Animated page grid for the Visual Organizer.

    Qt's built-in drag-and-drop is unreliable for list views in IconMode, so
    dragging is driven directly by mouse events: the pressed card follows the
    cursor while the other cards slide out of the way with a short animation.
    """

    orderChanged = pyqtSignal()
    selectionChanged = pyqtSignal(object)

    def __init__(self, document: fitz.Document, parent=None):
        super().__init__(parent)
        self.setObjectName("organizerGrid")
        self.setWidgetResizable(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._document = document
        # State is initialized before setWidget: QScrollArea delivers events
        # to the content widget during setWidget, and eventFilter() reads it.
        self._widgets: list[OrganizerPageWidget] = []
        self._selected: set[OrganizerPageWidget] = set()
        self._selection_anchor: OrganizerPageWidget | None = None
        self._rotations: dict[int, int] = {}
        self._columns = 1
        self._animations: dict[int, QPropertyAnimation] = {}
        self._drag: OrganizerPageWidget | None = None
        self._drag_offset = QPoint()
        self._press_pos = QPoint()
        self._dragging = False
        self._drag_slot: int | None = None
        self._thumb_queue: list[int] = []
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setInterval(0)
        self._thumb_timer.timeout.connect(self._load_thumbnail_batch)
        self._container = QWidget()
        self._container.setObjectName("organizerGridContainer")
        self.setWidget(self._container)
        self._insertion_line = QFrame(self._container)
        self._insertion_line.setObjectName("organizerInsertionLine")
        self._insertion_line.setFixedHeight(3)
        self._insertion_line.hide()
        self._insertion_line.raise_()
        self._container.installEventFilter(self)
        self.viewport().setMouseTracking(True)
        self.viewport().installEventFilter(self)
        for index in range(document.page_count):
            self._add_widget(index)
        self._relayout()

    # --- construction and layout -----------------------------------------
    def _add_widget(self, original_index: int) -> None:
        entry = PagePlanEntry(
            uuid.uuid4().hex,
            "current",
            original_index,
            final_rotation=int(self._document.load_page(original_index).rotation),
        )
        widget = OrganizerPageWidget(entry, self._container)
        self._widgets.append(widget)
        widget.installEventFilter(self)
        widget.show()
        self._thumb_queue.append(original_index)

    def _widget_by_original(self, original_index: int) -> OrganizerPageWidget | None:
        for widget in self._widgets:
            if widget.original_index == original_index:
                return widget
        return None

    def _slot_rect(self, slot: int) -> QRect:
        column = slot % self._columns
        row = slot // self._columns
        x = ORGANIZER_MARGIN + column * (ORGANIZER_CELL_W + ORGANIZER_SPACING)
        y = ORGANIZER_MARGIN + row * (ORGANIZER_CELL_H + ORGANIZER_SPACING)
        return QRect(x, y, ORGANIZER_CELL_W, ORGANIZER_CELL_H)

    def _relayout(self) -> None:
        viewport_width = max(240, self.viewport().width())
        self._columns = max(
            1,
            (viewport_width - ORGANIZER_MARGIN + ORGANIZER_SPACING)
            // (ORGANIZER_CELL_W + ORGANIZER_SPACING),
        )
        rows = max(1, (len(self._widgets) + self._columns - 1) // self._columns)
        height = (
            ORGANIZER_MARGIN * 2
            + rows * (ORGANIZER_CELL_H + ORGANIZER_SPACING)
            - ORGANIZER_SPACING
        )
        self._container.setFixedSize(viewport_width, height)
        for slot, widget in enumerate(self._widgets):
            widget.move(self._slot_rect(slot).topLeft())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    def _animate_to(self, widget: QWidget, target: QPoint, duration: int = 150) -> None:
        animation = self._animations.get(id(widget))
        if animation is None:
            animation = QPropertyAnimation(widget, b"pos", self)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._animations[id(widget)] = animation
        animation.stop()
        animation.setDuration(duration)
        animation.setStartValue(widget.pos())
        animation.setEndValue(target)
        animation.start()

    # --- selection --------------------------------------------------------
    def _set_selection(self, widgets) -> None:
        for widget in self._selected:
            widget.set_selected(False)
        self._selected = set(widgets)
        for widget in self._selected:
            widget.set_selected(True)
        self.selectionChanged.emit(tuple(widget.entry for widget in self._selected))
        self.viewport().update()

    # --- mouse-driven dragging --------------------------------------------
    def eventFilter(self, obj, event) -> bool:
        event_type = event.type()
        widgets = getattr(self, "_widgets", ())
        if obj in widgets:
            if event_type == QEvent.Type.KeyPress:
                self.keyPressEvent(event)
                return event.isAccepted()
            if (
                event_type == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self._handle_press(obj, event)
                return True
            if event_type == QEvent.Type.MouseMove and self._drag is obj:
                if self._handle_move(obj, event):
                    return True
            if (
                event_type == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
            ):
                if self._handle_release(obj, event):
                    return True
            return False
        if obj is self._container or obj is self.viewport():
            if (
                event_type == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self._set_selection([])
        return super().eventFilter(obj, event)

    def _handle_press(self, widget: OrganizerPageWidget, event) -> None:
        position = widget.mapTo(self._container, event.position().toPoint())
        self._drag = widget
        self._press_pos = position
        self._drag_offset = position - widget.pos()
        self._dragging = False
        self._drag_slot = None
        widget.setFocus(Qt.FocusReason.MouseFocusReason)
        modifiers = event.modifiers()
        if (
            modifiers & Qt.KeyboardModifier.ShiftModifier
            and self._selection_anchor in self._widgets
        ):
            first = self._widgets.index(self._selection_anchor)
            last = self._widgets.index(widget)
            low, high = sorted((first, last))
            self._set_selection(self._widgets[low : high + 1])
        elif modifiers & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        ):
            selected = set(self._selected)
            if widget in selected:
                selected.remove(widget)
            else:
                selected.add(widget)
            self._set_selection(selected)
            self._selection_anchor = widget
        else:
            self._set_selection([widget])
            self._selection_anchor = widget

    def _handle_move(self, widget: OrganizerPageWidget, event) -> bool:
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            self._cancel_drag()
            return False
        position = widget.mapTo(self._container, event.position().toPoint())
        if not self._dragging:
            if (
                position - self._press_pos
            ).manhattanLength() < QApplication.startDragDistance():
                return False
            self._dragging = True
            widget.raise_()
            widget.set_lifted(True)
        widget.move(position - self._drag_offset)
        self._maybe_autoscroll(widget, event)
        center = position - self._drag_offset + QPoint(
            ORGANIZER_CELL_W // 2, ORGANIZER_CELL_H // 2
        )
        slot = self._slot_at(center)
        if slot is None or slot == self._drag_slot:
            return True
        self._drag_slot = slot
        indicator = self._slot_rect(slot)
        self._insertion_line.setGeometry(indicator.x(), indicator.y() - 4, indicator.width(), 3)
        self._insertion_line.show()
        self._insertion_line.raise_()
        order = [item for item in self._widgets if item is not widget]
        order.insert(min(slot, len(order)), widget)
        self._widgets = order
        for index, other in enumerate(order):
            if other is widget:
                continue
            target = self._slot_rect(index).topLeft()
            if other.pos() != target:
                self._animate_to(other, target, 130)
        return True

    def _handle_release(self, widget: OrganizerPageWidget, event) -> bool:
        if not self._dragging:
            self._drag = None
            self._insertion_line.hide()
            return False
        widget.set_lifted(False)
        slot = self._widgets.index(widget)
        self._animate_to(widget, self._slot_rect(slot).topLeft(), 170)
        self._dragging = False
        self._drag_slot = None
        self._drag = None
        self._insertion_line.hide()
        self.orderChanged.emit()
        return True

    def _cancel_drag(self) -> None:
        if self._drag is not None:
            self._drag.set_lifted(False)
        self._insertion_line.hide()
        self._drag = None
        self._dragging = False
        self._drag_slot = None

    def _slot_at(self, position: QPoint) -> int | None:
        column = (position.x() - ORGANIZER_MARGIN) // (
            ORGANIZER_CELL_W + ORGANIZER_SPACING
        )
        row = (position.y() - ORGANIZER_MARGIN) // (ORGANIZER_CELL_H + ORGANIZER_SPACING)
        if column < 0 or column >= self._columns or row < 0:
            return None
        slot = row * self._columns + column
        return slot if slot < len(self._widgets) else None

    def _maybe_autoscroll(self, widget: OrganizerPageWidget, event) -> None:
        viewport_position = widget.mapTo(self.viewport(), event.position().toPoint())
        bar = self.verticalScrollBar()
        if viewport_position.y() < 24:
            bar.setValue(bar.value() - 28)
        elif viewport_position.y() > self.viewport().height() - 24:
            bar.setValue(bar.value() + 28)

    # --- thumbnails --------------------------------------------------------
    def _load_thumbnail_batch(self) -> None:
        for _ in range(6):
            if not self._thumb_queue:
                self._thumb_timer.stop()
                return
            original = self._thumb_queue.pop(0)
            widget = self._widget_by_original(original)
            if widget is not None:
                self._render_thumbnail(widget)

    def _render_thumbnail(self, widget: OrganizerPageWidget) -> None:
        if widget.entry.source_kind == "external":
            with fitz.open(widget.entry.source_path) as source:
                if source.needs_pass:
                    source.authenticate(widget.entry.password)
                page = source.load_page(widget.entry.source_page)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(0.22, 0.22), alpha=False)
        else:
            page = self._document.load_page(widget.entry.source_page)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(0.22, 0.22), alpha=False)
        image = _fitz_pixmap_image(pixmap)
        if widget.rotation_delta:
            image = image.transformed(QTransform().rotate(widget.rotation_delta))
        thumbnail = QPixmap.fromImage(image).scaled(
            ORGANIZER_THUMB_W,
            ORGANIZER_THUMB_H,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        canvas = QPixmap(ORGANIZER_THUMB_W, ORGANIZER_THUMB_H)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.drawPixmap(
            (canvas.width() - thumbnail.width()) // 2,
            (canvas.height() - thumbnail.height()) // 2,
            thumbnail,
        )
        painter.end()
        widget.set_thumbnail(canvas)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._thumb_queue:
            self._thumb_timer.start()

    def stop_timer(self) -> None:
        self._thumb_timer.stop()

    def shutdown(self) -> None:
        """Stop timers, drags and animations before the dialog is destroyed."""
        self._thumb_timer.stop()
        self._cancel_drag()
        for animation in list(self._animations.values()):
            animation.stop()
        self._animations.clear()

    # --- public operations used by the dialog -----------------------------
    def count(self) -> int:
        return len(self._widgets)

    def selected_widgets(self) -> list[OrganizerPageWidget]:
        return sorted(self._selected, key=self._widgets.index)

    def select_source_pages(self, pages: tuple[int, ...] | list[int]) -> None:
        wanted = set(pages)
        selected = [
            widget
            for widget in self._widgets
            if widget.entry.source_kind == "current"
            and widget.entry.source_page in wanted
        ]
        self._set_selection(selected)
        self._selection_anchor = selected[0] if selected else None

    def rotate_selected(self, amount: int) -> None:
        for widget in list(self._selected):
            widget.rotate(amount)
            if widget.entry.source_kind == "current":
                self._rotations[widget.original_index] = widget.rotation_delta
            self._render_thumbnail(widget)
        self.orderChanged.emit()

    def duplicate_selected(self) -> bool:
        selected = self.selected_widgets()
        if not selected:
            return False
        insertion = self._widgets.index(selected[-1]) + 1
        copies: list[OrganizerPageWidget] = []
        for original in selected:
            entry = replace(original.entry, entry_id=uuid.uuid4().hex)
            widget = OrganizerPageWidget(entry, self._container)
            widget.rotation_delta = original.rotation_delta
            widget.set_rotation(original.rotation_delta)
            widget.set_thumbnail(original._thumb.pixmap())
            widget.installEventFilter(self)
            widget.show()
            copies.append(widget)
        self._widgets[insertion:insertion] = copies
        self._relayout()
        self._set_selection(copies)
        self._selection_anchor = copies[0]
        self.orderChanged.emit()
        return True

    def add_external_pages(
        self, entries: list[PagePlanEntry], position: str = "after"
    ) -> None:
        widgets: list[OrganizerPageWidget] = []
        for entry in entries:
            widget = OrganizerPageWidget(entry, self._container)
            widget.installEventFilter(self)
            widget.show()
            self._render_thumbnail(widget)
            widgets.append(widget)
        selected = self.selected_widgets()
        if position == "beginning":
            insertion = 0
        elif position == "end" or not selected:
            insertion = len(self._widgets)
        elif position == "before":
            insertion = self._widgets.index(selected[0])
        else:
            insertion = self._widgets.index(selected[-1]) + 1
        self._widgets[insertion:insertion] = widgets
        self._relayout()
        self._set_selection(widgets)
        self._selection_anchor = widgets[0] if widgets else None
        self.orderChanged.emit()

    def replace_selected(self, entries: list[PagePlanEntry]) -> bool:
        selected = self.selected_widgets()
        if not selected or not entries:
            return False
        positions = [self._widgets.index(widget) for widget in selected]
        if positions != list(range(min(positions), max(positions) + 1)):
            return False
        insertion = positions[0]
        for widget in selected:
            self._widgets.remove(widget)
            widget.setParent(None)
            widget.deleteLater()
        self._selected.clear()
        self.add_external_pages(entries, "end")
        added = self.selected_widgets()
        for widget in added:
            self._widgets.remove(widget)
        self._widgets[insertion:insertion] = added
        self._relayout()
        self._set_selection(added)
        self.orderChanged.emit()
        return True

    def remove_selected(self) -> bool:
        if len(self._widgets) - len(self._selected) < 1:
            return False
        for widget in list(self._selected):
            self._selected.discard(widget)
            self._widgets.remove(widget)
            widget.setParent(None)
            widget.deleteLater()
        remaining = {widget.original_index for widget in self._widgets}
        self._rotations = {
            original: rotation
            for original, rotation in self._rotations.items()
            if original in remaining
        }
        self._selection_anchor = None
        self._relayout()
        self.selectionChanged.emit(())
        self.orderChanged.emit()
        return True

    def restore(self) -> None:
        self._thumb_timer.stop()
        for widget in self._widgets:
            widget.setParent(None)
            widget.deleteLater()
        self._widgets.clear()
        self._selected.clear()
        self._selection_anchor = None
        self._rotations.clear()
        self._thumb_queue.clear()
        for index in range(self._document.page_count):
            self._add_widget(index)
        self._relayout()
        if self.isVisible() and self._thumb_queue:
            self._thumb_timer.start()
        self.selectionChanged.emit(())
        self.orderChanged.emit()

    def order(self) -> list[int]:
        return [widget.entry.source_page for widget in self._widgets]

    def page_plan(self) -> list[PagePlanEntry]:
        return [widget.entry for widget in self._widgets]

    def rotations(self) -> dict[int, int]:
        return dict(self._rotations)

    # --- keyboard reordering ----------------------------------------------
    def keyPressEvent(self, event) -> None:
        modifiers = event.modifiers()
        toggle_modifier = modifiers & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        )
        if toggle_modifier and event.key() == Qt.Key.Key_A:
            self._set_selection(self._widgets)
            self._selection_anchor = self._widgets[0] if self._widgets else None
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self._set_selection([])
            self._selection_anchor = None
            event.accept()
            return
        focused = QApplication.focusWidget()
        widget = (
            focused
            if isinstance(focused, OrganizerPageWidget) and focused in self._widgets
            else (self.selected_widgets()[0] if self._selected else None)
        )
        if widget is None and self._widgets:
            widget = self._widgets[0]
        if event.key() == Qt.Key.Key_Space and widget is not None:
            selected = set(self._selected)
            if widget in selected:
                selected.remove(widget)
            else:
                selected.add(widget)
            self._set_selection(selected)
            self._selection_anchor = widget
            event.accept()
            return
        if event.key() not in (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
        ) or widget is None:
            super().keyPressEvent(event)
            return
        index = self._widgets.index(widget)
        step = {
            Qt.Key.Key_Left: -1,
            Qt.Key.Key_Right: 1,
            Qt.Key.Key_Up: -self._columns,
            Qt.Key.Key_Down: self._columns,
        }[event.key()]
        target = max(0, min(len(self._widgets) - 1, index + step))
        if toggle_modifier and len(self._selected) == 1:
            self._widgets[index], self._widgets[target] = (
                self._widgets[target],
                self._widgets[index],
            )
            self._relayout()
            self.orderChanged.emit()
        else:
            target_widget = self._widgets[target]
            target_widget.setFocus(Qt.FocusReason.TabFocusReason)
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                anchor = self._selection_anchor or widget
                low, high = sorted(
                    (self._widgets.index(anchor), self._widgets.index(target_widget))
                )
                self._set_selection(self._widgets[low : high + 1])
            else:
                self._set_selection([target_widget])
                self._selection_anchor = target_widget
        event.accept()


class VisualOrganizerDialog(ToolDialog):
    """PageEntry-based insert, replace, duplicate, reorder and delete plan."""

    def __init__(
        self,
        document: fitz.Document,
        parent=None,
        *,
        preselected_pages: tuple[int, ...] = (),
    ):
        super().__init__("Organize Pages", "organize-pages", parent)
        self.document = document
        self.rotations: dict[int, int] = {}
        self.order: list[int] = []
        self.page_plan: list[PagePlanEntry] = []
        self._preselected_pages = preselected_pages

        intro = QLabel(
            "Build a page plan by dragging or using the toolbar. Nothing changes "
            "until Apply; destructive actions require this final confirmation."
        )
        intro.setObjectName("secondary")
        intro.setWordWrap(True)
        self._root.addWidget(intro)

        toolbar = QHBoxLayout()
        self.insert_position = QComboBox()
        for label, value in (
            ("After selection", "after"),
            ("Before selection", "before"),
            ("Beginning", "beginning"),
            ("End", "end"),
        ):
            self.insert_position.addItem(label, value)
        toolbar.addWidget(self.insert_position)
        for label, callback in (
            ("Insert", self._insert_external),
            ("Replace", self._replace_external),
            ("Duplicate", self._duplicate),
            ("Extract", self._extract_selected),
            ("Delete", self._remove_selected),
            ("Rotate left", lambda: self._rotate_selected(-90)),
            ("Rotate right", lambda: self._rotate_selected(90)),
            ("Restore", self._restore),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        self._root.addLayout(toolbar)

        self.pages = OrganizerGrid(document)
        self.pages.orderChanged.connect(self._update_summary)
        self.pages.selectionChanged.connect(lambda _entries: self._update_summary())
        self._root.addWidget(self.pages, 1)

        actions = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setMinimumWidth(210)
        actions.addStretch(1)
        actions.addWidget(self.summary)
        self._root.addLayout(actions)
        self.add_validation()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
        )
        self.apply_button = buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply_button.setText("Apply Page Plan")
        self.apply_button.clicked.connect(self._accept_changes)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)
        self._restore()
        if preselected_pages:
            self.pages.select_source_pages(preselected_pages)

    def _restore(self) -> None:
        self.pages.restore()
        if self._preselected_pages:
            self.pages.select_source_pages(self._preselected_pages)
        self._update_summary()

    def _rotate_selected(self, amount: int) -> None:
        self.pages.rotate_selected(amount)

    def _remove_selected(self) -> None:
        if not self.pages.selected_widgets():
            self.show_error("Select one or more pages first.")
            return
        if not self.pages.remove_selected():
            self.show_error("A PDF must keep at least one page.")
            return
        self._update_summary()

    def _duplicate(self) -> None:
        if not self.pages.duplicate_selected():
            self.show_error("Select one or more pages to duplicate.")

    def _source_entries(self) -> list[PagePlanEntry]:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose source PDF", "", "PDF (*.pdf)"
        )
        if not path:
            return []
        password = ""
        try:
            with fitz.open(path) as source:
                if source.needs_pass:
                    password, accepted = QInputDialog.getText(
                        self,
                        "Encrypted source PDF",
                        "Password",
                        QLineEdit.EchoMode.Password,
                    )
                    if not accepted:
                        return []
                    if not source.authenticate(password):
                        self.show_error("The source PDF password is not valid.")
                        return []
                value, accepted = QInputDialog.getText(
                    self,
                    "Source pages",
                    f"Pages (1-{source.page_count})",
                    text=f"1-{source.page_count}",
                )
                if not accepted:
                    return []
                pages = parse_page_range(value, source.page_count)
                if not pages:
                    self.show_error("Choose at least one valid source page.")
                    return []
                return [
                    PagePlanEntry(
                        uuid.uuid4().hex,
                        "external",
                        page,
                        str(Path(path).resolve()),
                        int(source.load_page(page).rotation),
                        password,
                    )
                    for page in pages
                ]
        except Exception as exc:
            self.show_error(f"Cannot read source PDF: {exc}")
            return []

    def _insert_external(self) -> None:
        entries = self._source_entries()
        if entries:
            self.pages.add_external_pages(
                entries, str(self.insert_position.currentData())
            )

    def _replace_external(self) -> None:
        selected = self.pages.selected_widgets()
        positions = [self.pages._widgets.index(widget) for widget in selected]
        if not positions or positions != list(range(min(positions), max(positions) + 1)):
            self.show_error("Replace requires one contiguous page selection.")
            return
        entries = self._source_entries()
        if entries and not self.pages.replace_selected(entries):
            self.show_error("The selected pages could not be replaced.")

    def _extract_selected(self) -> None:
        selected = self.pages.selected_widgets()
        if not selected:
            self.show_error("Select one or more pages to extract.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Extract selected pages", "extracted-pages.pdf", "PDF (*.pdf)"
        )
        if not path:
            return
        if not path.casefold().endswith(".pdf"):
            path += ".pdf"
        try:
            with fitz.open() as output:
                for widget in selected:
                    entry = widget.entry
                    if entry.source_kind == "current":
                        output.insert_pdf(
                            self.document,
                            from_page=entry.source_page,
                            to_page=entry.source_page,
                        )
                    else:
                        with fitz.open(entry.source_path) as source:
                            if source.needs_pass:
                                source.authenticate(entry.password)
                            output.insert_pdf(
                                source,
                                from_page=entry.source_page,
                                to_page=entry.source_page,
                            )
                output.save(path, garbage=3, deflate=True)
        except Exception as exc:
            self.show_error(f"Extract failed: {exc}")

    def _update_summary(self) -> None:
        selected = len(self.pages.selected_widgets())
        self.summary.setText(
            f"{selected} page{'s' if selected != 1 else ''} selected · "
            f"{self.pages.count()} final pages"
        )

    def _accept_changes(self) -> None:
        if self.pages.count() < 1:
            self.show_error("A PDF must keep at least one page.")
            return
        self.order = self.pages.order()
        self.rotations = self.pages.rotations()
        self.page_plan = self.pages.page_plan()
        self.accept()

    def done(self, result: int) -> None:
        self.pages.shutdown()
        super().done(result)

    def reject(self) -> None:
        self.pages.shutdown()
        super().reject()

    def closeEvent(self, event) -> None:
        self.pages.shutdown()
        super().closeEvent(event)


class DocumentInfoDialog(ToolDialog):
    def __init__(self, document: fitz.Document, path: Path | None, parent=None):
        super().__init__("Document Information", "document-info", parent)
        self.document = document
        self.path = path
        # The Fonts/Images/Text tabs scan every page, which freezes the UI on
        # large PDFs; build them lazily when the user first opens each tab.
        self.tabs = QTabWidget()
        self.tabs.addTab(self._general_tab(), "General")
        self._lazy_builders = {
            "Fonts": self._fonts_tab,
            "Images": self._images_tab,
            "Text": self._text_tab,
        }
        self._built_tabs: set[int] = {0}
        for label in ("Fonts", "Images", "Text"):
            placeholder = QWidget()
            placeholder_layout = QVBoxLayout(placeholder)
            hint = QLabel(f"Scanning {label.lower()}…")
            hint.setObjectName("secondary")
            placeholder_layout.addWidget(hint)
            placeholder_layout.addStretch(1)
            self.tabs.addTab(placeholder, label)
        self.tabs.currentChanged.connect(self._ensure_tab_built)
        self._root.addWidget(self.tabs, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)

    def _ensure_tab_built(self, index: int) -> None:
        if index in self._built_tabs or index <= 0:
            return
        self._built_tabs.add(index)
        label = self.tabs.tabText(index)
        builder = self._lazy_builders.get(label)
        if builder is None:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            widget = builder()
            self.tabs.removeTab(index)
            self.tabs.insertTab(index, widget, label)
            self.tabs.setCurrentIndex(index)
        finally:
            QApplication.restoreOverrideCursor()

    def _general_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        metadata = dict(self.document.metadata or {})
        size = self.path.stat().st_size if self.path and self.path.exists() else 0
        encrypted = bool(self.document.needs_pass)
        values = (
            ("File", str(self.path or "—")),
            ("File size", f"{size / 1048576:.2f} MB" if size else "—"),
            ("Pages", str(self.document.page_count)),
            ("PDF format", str(metadata.get("format") or "—")),
            ("Encrypted", "Yes" if encrypted else "No"),
            ("Title", str(metadata.get("title") or "—")),
            ("Author", str(metadata.get("author") or "—")),
            ("Subject", str(metadata.get("subject") or "—")),
            ("Keywords", str(metadata.get("keywords") or "—")),
            ("Creator", str(metadata.get("creator") or "—")),
            ("Producer", str(metadata.get("producer") or "—")),
            ("Created", str(metadata.get("creationDate") or "—")),
            ("Modified", str(metadata.get("modDate") or "—")),
        )
        for label, value in values:
            field = QLabel(value)
            field.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            field.setWordWrap(True)
            form.addRow(label, field)
        return tab

    def _table(self, headers: list[str]) -> SortableTableWidget:
        table = SortableTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setDefaultSectionSize(32)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    @staticmethod
    def _append(table: SortableTableWidget, values: list[object]) -> None:
        row = table.rowCount()
        table.insertRow(row)
        for column, value in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(str(value)))

    def _fonts_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        table = self._table(["Font", "Type", "Encoding", "Pages", "Embedded"])
        found: dict[tuple[str, str, str, str], set[int]] = {}
        for page_index in range(self.document.page_count):
            for font in self.document.load_page(page_index).get_fonts(full=True):
                embedded = "Yes" if str(font[1]).casefold() not in {"", "n/a"} else "No"
                key = (
                    str(font[3] or font[4] or "Unknown"),
                    str(font[2]),
                    str(font[5]),
                    embedded,
                )
                found.setdefault(key, set()).add(page_index + 1)
        for (name, type_, encoding, embedded), pages in sorted(found.items()):
            self._append(
                table,
                [name, type_, encoding, ", ".join(map(str, pages)), embedded],
            )
        layout.addWidget(QLabel(f"{len(found)} unique font resource(s)"))
        layout.addWidget(table, 1)
        return tab

    def _images_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        table = self._table(["Page", "Width", "Height", "Bits", "Colour space", "Filter"])
        count = 0
        for page_index in range(self.document.page_count):
            for image in self.document.load_page(page_index).get_images(full=True):
                self._append(table, [page_index + 1, image[2], image[3], image[4], image[5], image[8]])
                count += 1
        layout.addWidget(QLabel(f"{count} image occurrence(s)"))
        layout.addWidget(table, 1)
        return tab

    def _text_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        table = self._table(["Page", "Characters", "Words", "Text blocks"])
        total_characters = total_words = total_blocks = 0
        for page_index in range(self.document.page_count):
            page = self.document.load_page(page_index)
            text = page.get_text()
            characters = len(text)
            words = len(text.split())
            blocks = len(page.get_text("blocks"))
            total_characters += characters
            total_words += words
            total_blocks += blocks
            self._append(table, [page_index + 1, characters, words, blocks])
        layout.addWidget(
            QLabel(
                f"{total_characters:,} characters · {total_words:,} words · "
                f"{total_blocks:,} text blocks"
            )
        )
        layout.addWidget(table, 1)
        return tab


class PrintOptionsDialog(ToolDialog):
    def __init__(self, page_count: int, current_page: int, parent=None):
        super().__init__("Print PDF", "print-options", parent)
        self.page_count = page_count
        self.current_page = current_page
        self.details: dict[str, object] | None = None

        printer_group = QGroupBox("Printer")
        printer_form = QFormLayout(printer_group)
        self.printer = QComboBox()
        default_name = QPrinterInfo.defaultPrinterName()
        for printer in QPrinterInfo.availablePrinters():
            self.printer.addItem(printer.printerName())
        if default_name:
            index = self.printer.findText(default_name)
            if index >= 0:
                self.printer.setCurrentIndex(index)
        self.copies = QSpinBox()
        self.copies.setRange(1, 999)
        self.collate = QCheckBox("Collate multiple copies")
        self.collate.setChecked(True)
        self.colour = QComboBox()
        self.colour.addItems(["Colour", "Grayscale"])
        self.duplex = QComboBox()
        self.duplex.addItems(["Printer default", "Single-sided", "Duplex — long edge", "Duplex — short edge"])
        self.quality = QComboBox()
        self.quality.addItem("Draft — 150 DPI", 150)
        self.quality.addItem("Standard — 300 DPI", 300)
        self.quality.addItem("High — 600 DPI", 600)
        self.quality.addItem("Custom DPI", None)
        self.quality.setCurrentIndex(1)
        self.quality_dpi = QSpinBox()
        self.quality_dpi.setRange(72, 600)
        self.quality_dpi.setValue(300)
        self.quality_dpi.setSuffix(" DPI")
        self.quality_dpi.setToolTip(
            "Higher DPI produces sharper output but uses more memory and takes longer."
        )
        self.quality.currentIndexChanged.connect(self._quality_changed)
        self._quality_changed(self.quality.currentIndex())
        self.confirm_system = QCheckBox("Confirm with the system dialog")
        self.confirm_system.setToolTip(
            "When unchecked, the document prints directly with the options above."
        )
        self.confirm_system.setChecked(False)
        printer_form.addRow("Printer", self.printer)
        printer_form.addRow("Copies", self.copies)
        printer_form.addRow("", self.collate)
        printer_form.addRow("Output", self.colour)
        printer_form.addRow("Two-sided", self.duplex)
        printer_form.addRow("Print quality", self.quality)
        printer_form.addRow("Custom quality", self.quality_dpi)
        printer_form.addRow("", self.confirm_system)
        self._root.addWidget(printer_group)

        content = QHBoxLayout()
        pages_group = QGroupBox("Pages")
        pages_form = QFormLayout(pages_group)
        self.all_pages = QRadioButton(f"All pages (1–{page_count})")
        self.current = QRadioButton(f"Current page ({current_page + 1})")
        self.custom = QRadioButton("Custom range")
        self.range = QTextEdit()
        self.range.setPlaceholderText("e.g. 1-3, 5, 8-10")
        self.range.setMaximumHeight(62)
        self.range.setEnabled(False)
        self.custom.toggled.connect(self.range.setEnabled)
        self.all_pages.setChecked(True)
        pages_form.addRow(self.all_pages)
        pages_form.addRow(self.current)
        pages_form.addRow(self.custom)
        pages_form.addRow("Page range", self.range)
        content.addWidget(pages_group)

        layout_group = QGroupBox("Paper and placement")
        layout_form = QFormLayout(layout_group)
        self.paper = QComboBox()
        self.paper.addItems(["PDF page size", "A4", "A3", "A5", "Letter"])
        self.orientation = QComboBox()
        self.orientation.addItems(["Automatic", "Portrait", "Landscape"])
        self.scale_mode = QComboBox()
        self.scale_mode.addItems(["Fit to printable area", "Actual size", "Custom scale"])
        self.scale = QSpinBox()
        self.scale.setRange(10, 400)
        self.scale.setValue(100)
        self.scale.setSuffix(" %")
        self.scale.setEnabled(False)
        self.scale_mode.currentIndexChanged.connect(lambda index: self.scale.setEnabled(index == 2))
        self.center = QCheckBox("Centre on page")
        self.center.setChecked(True)
        # Four-edge shifts (legacy layout) pre-filled from the saved
        # preferences so printer-specific offsets need not be re-entered.
        left_mm, right_mm, top_mm, bottom_mm = self._default_offsets()
        self.offset_left = self._offset_spin(left_mm)
        self.offset_right = self._offset_spin(right_mm)
        self.offset_top = self._offset_spin(top_mm)
        self.offset_bottom = self._offset_spin(bottom_mm)
        layout_form.addRow("Paper", self.paper)
        layout_form.addRow("Orientation", self.orientation)
        layout_form.addRow("Scaling", self.scale_mode)
        layout_form.addRow("Custom scale", self.scale)
        layout_form.addRow("", self.center)
        layout_form.addRow("Shift from left", self.offset_left)
        layout_form.addRow("Shift from right", self.offset_right)
        layout_form.addRow("Shift from top", self.offset_top)
        layout_form.addRow("Shift from bottom", self.offset_bottom)
        paper_note = QLabel(
            "One print job uses one paper size. “PDF page size” follows the first selected page."
        )
        paper_note.setObjectName("secondary")
        paper_note.setWordWrap(True)
        layout_form.addRow("", paper_note)
        content.addWidget(layout_group)
        self._root.addLayout(content, 1)
        self._restore_profile()
        self.add_validation()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Print")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)

    @staticmethod
    def _offset_spin(value: float) -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setRange(-100, 100)
        control.setDecimals(1)
        control.setSuffix(" mm")
        control.setValue(value)
        return control

    def _default_offsets(self) -> tuple[float, float, float, float]:
        settings = getattr(self.parent(), "settings", None)
        if settings is not None:
            return settings.get_print_offsets()
        return (0.0, 0.0, 0.0, 0.0)

    def _default_profile(self) -> dict[str, object]:
        settings = getattr(self.parent(), "settings", None)
        if settings is not None:
            return settings.get_print_profile()
        return {}

    def _quality_changed(self, _index: int) -> None:
        quality_changed(self)

    def _selected_quality_dpi(self) -> int:
        return selected_quality_dpi(self)

    def _restore_profile(self) -> None:
        profile = self._default_profile()
        restore_print_profile(self, profile)
        mode = str(profile.get("page_mode", "all"))
        if mode == "current":
            self.current.setChecked(True)
        elif mode == "custom":
            self.custom.setChecked(True)
        else:
            self.all_pages.setChecked(True)
        self.range.setPlainText(str(profile.get("page_range", "")))

    def _validate(self) -> None:
        if not self.printer.currentText():
            self.show_error("No printer is available on this system.")
            return
        if self.all_pages.isChecked():
            pages = list(range(self.page_count))
        elif self.current.isChecked():
            pages = [self.current_page]
        else:
            try:
                pages = parse_page_range(self.range.toPlainText(), self.page_count)
            except ValueError as exc:
                self.show_error(str(exc))
                return
        if not pages:
            self.show_error("Choose at least one valid page to print.")
            return
        details = collect_print_profile(self)
        details.update(
            {
                "pages": pages,
                "page_mode": (
                    "all"
                    if self.all_pages.isChecked()
                    else "current"
                    if self.current.isChecked()
                    else "custom"
                ),
                "page_range": self.range.toPlainText(),
            }
        )
        self.details = details
        self.accept()
