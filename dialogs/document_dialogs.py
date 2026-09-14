"""Detailed document inspection, visual organization, and print options."""

from __future__ import annotations

import uuid
from collections import OrderedDict
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
from PyQt6.QtGui import QImage, QPixmap
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
    QGridLayout,
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

from core.diagnostics import log_failure
from core.page_plan import (
    PlanReader,
    SourceStore,
    blank_entry,
    duplicate_entries,
    export_plan,
    parse_page_selection,
    reverse_selected,
)
from core.pdf_engine import DOCUMENT_LOCK, PagePlanEntry, parse_page_range

from .base import SortableTableWidget, ToolDialog
from .organizer_tools import BlankPagesDialog, CropDialog, InterleaveDialog, SplitPlanDialog, run_job
from .print_profile import collect_print_profile, quality_changed, restore_print_profile, selected_quality_dpi


def _fitz_pixmap_image(pixmap: fitz.Pixmap) -> QImage:
    format_ = QImage.Format.Format_RGBA8888 if pixmap.alpha else QImage.Format.Format_RGB888
    return QImage(
        pixmap.samples, pixmap.width, pixmap.height, pixmap.stride, format_
    ).copy()


ORGANIZER_CELL_W = 164
ORGANIZER_CELL_H = 228
ORGANIZER_THUMB_W = 132
ORGANIZER_THUMB_H = 160
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
        self._thumb_slot = QWidget()
        self._thumb_slot.setFixedSize(ORGANIZER_THUMB_W, ORGANIZER_THUMB_H)
        slot_layout = QVBoxLayout(self._thumb_slot)
        slot_layout.setContentsMargins(0, 0, 0, 0)
        slot_layout.addWidget(self._thumb, 0, Qt.AlignmentFlag.AlignCenter)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._thumb_slot, 0, Qt.AlignmentFlag.AlignHCenter)
        self._caption = QLabel(self._label())
        self._caption.setObjectName("organizerPageCaption")
        self._caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._caption)
        self._dimensions = QLabel()
        self._dimensions.setObjectName("organizerPageCaption")
        self._dimensions.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._dimensions)
        self._badge = QLabel("✓", self)
        self._badge.setObjectName("organizerSelectionBadge")
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setFixedSize(24, 24)
        self._badge.move(132, 6)
        self._badge.hide()

    def _label(self) -> str:
        if self.entry.source_kind == "blank":
            return "Blank page"
        if self.entry.source_kind == "external":
            source = self.entry.source_label or Path(self.entry.source_path).name
            return f"{source} · p{self.entry.source_page + 1}"
        return f"Page {self.entry.source_page + 1}"

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        if not pixmap.isNull():
            self._thumb.setFixedSize(round(pixmap.width() / pixmap.devicePixelRatio()),
                                     round(pixmap.height() / pixmap.devicePixelRatio()))
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
        self.reader = PlanReader(document)
        self._thumb_cache = OrderedDict()
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
        self._thumb_queue: list[str] = []
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setInterval(10)
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
        self.verticalScrollBar().valueChanged.connect(self._queue_visible)

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
            widget._caption.setText(f"{slot + 1} · {widget._label()}")
            width, height = self.reader.size(widget.entry)
            widget._dimensions.setText(f"{width * 25.4 / 72:.0f} × {height * 25.4 / 72:.0f} mm · {widget.entry.final_rotation % 360}°")
            widget.setToolTip(f"{widget._caption.text()}\n{widget._dimensions.text()}")
            scale = min(ORGANIZER_THUMB_W / width, ORGANIZER_THUMB_H / height)
            widget._thumb.setFixedSize(max(1, round(width * scale)), max(1, round(height * scale)))
            if getattr(widget, "_thumbnail_key", None) != widget.entry:
                widget._thumb.clear()
        self._queue_visible()

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
        self._relayout()
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
    def _queue_visible(self, *_args) -> None:
        if not hasattr(self, "_thumb_timer") or not self.isVisible():
            return
        area = self.viewport().rect().translated(0, self.verticalScrollBar().value()).adjusted(0, -228, 0, 228)
        self._thumb_queue = []
        for widget in self._widgets:
            if widget.geometry().intersects(area):
                if getattr(widget, "_thumbnail_key", None) != widget.entry:
                    self._thumb_queue.append(widget.entry.entry_id)
            else:
                widget._thumb.clear()
                widget._thumbnail_key = None
        if self._thumb_queue:
            self._thumb_timer.start()

    def _load_thumbnail_batch(self) -> None:
        for _ in range(2):
            if not self._thumb_queue:
                self._thumb_timer.stop()
                return
            entry_id = self._thumb_queue.pop(0)
            widget = next((w for w in self._widgets if w.entry.entry_id == entry_id), None)
            if widget is not None:
                self._render_thumbnail(widget)

    def _render_thumbnail(self, widget: OrganizerPageWidget) -> None:
        key = widget.entry
        cached = self._thumb_cache.get(key)
        if cached is None:
            try:
                with DOCUMENT_LOCK:
                    image = _fitz_pixmap_image(self.reader.render(key, ORGANIZER_THUMB_H))
                cached = QPixmap.fromImage(image).scaled(
                    ORGANIZER_THUMB_W, ORGANIZER_THUMB_H,
                    Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
                )
                self._thumb_cache[key] = cached
                while len(self._thumb_cache) > 128:
                    self._thumb_cache.popitem(last=False)
            except Exception as exc:
                log_failure('document_dialogs._render_thumbnail: fallback after failure', 10)
                widget._thumb.setText("Preview unavailable")
                widget.setToolTip(str(exc))
                return
        self._thumb_cache.move_to_end(key)
        widget.set_thumbnail(cached)
        widget._thumbnail_key = key

    def set_plan(self, entries: list[PagePlanEntry], selected_ids=None) -> None:
        self._thumb_timer.stop()
        self._cancel_drag()
        for animation in self._animations.values():
            animation.stop()
        previous = {w.entry.entry_id: w for w in self._widgets}
        selected_ids = set(selected_ids if selected_ids is not None else (w.entry.entry_id for w in self._selected))
        self._selected.clear()
        widgets = []
        for entry in entries:
            widget = previous.pop(entry.entry_id, None)
            if widget is None:
                widget = OrganizerPageWidget(entry, self._container)
                widget.installEventFilter(self)
            widget.entry = entry
            widget.original_index = entry.source_page if entry.source_kind == "current" else -1
            widget.set_selected(False)
            widget.show()
            widgets.append(widget)
        for widget in previous.values():
            widget.setParent(None)
            widget.deleteLater()
        self._widgets = widgets
        self._selection_anchor = None
        self._rotations = {}
        self._relayout()
        self._set_selection(w for w in widgets if w.entry.entry_id in selected_ids)
        self.orderChanged.emit()

    def selected_positions(self) -> list[int]:
        return [i for i, w in enumerate(self._widgets) if w in self._selected]

    def select_positions(self, positions) -> None:
        selected = [self._widgets[i] for i in positions]
        self._set_selection(selected)
        self._selection_anchor = selected[0] if selected else None

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._queue_visible()

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
        self._relayout()
        self.orderChanged.emit()

    def duplicate_selected(self) -> bool:
        selected = self.selected_widgets()
        if not selected:
            return False
        insertion = self._widgets.index(selected[-1]) + 1
        copies: list[OrganizerPageWidget] = []
        for original in selected:
            entry = duplicate_entries([original.entry])[0]
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
        plan = self.page_plan()
        plan[positions[0]:positions[-1] + 1] = entries
        self.set_plan(plan, {entry.entry_id for entry in entries})
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
        if toggle_modifier and event.key() == Qt.Key.Key_A and not getattr(self, "_command_selection_bound", False):
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
        super().__init__("Advanced Page Organizer", "organize-pages", parent)
        self.document = document
        self.rotations: dict[int, int] = {}
        self.order: list[int] = []
        self.page_plan: list[PagePlanEntry] = []
        self._preselected_pages = preselected_pages
        self.sources = SourceStore()
        self.protected_paths = {Path(document.name).resolve()} if document.name else set()
        self._busy = False
        self._history = []
        self._history_index = -1
        self._replaying = False

        self.setObjectName("advancedOrganizer")
        self.setMinimumSize(780, 620)
        self.resize(max(self.width(), 1000), max(self.height(), 740))
        title = QLabel("Advanced Page Organizer")
        title.setObjectName("organizerTitle")
        self._root.addWidget(title)
        intro = QLabel("Select pages, build your preview, then Apply. The original document stays unchanged until you apply.")
        intro.setObjectName("secondary")
        intro.setWordWrap(True)
        self._root.addWidget(intro)

        selection = QGroupBox("Select pages")
        selection_layout = QVBoxLayout(selection)
        select_row = QHBoxLayout()
        self.selection_input = QLineEdit()
        self.selection_input.setPlaceholderText("1-10,15  |  odd  |  every 4th page  |  last 10 pages")
        self.selection_input.returnPressed.connect(self._select_expression)
        select_row.addWidget(self.selection_input, 1)
        select_row.addWidget(self._action_button("Select", self._select_expression))
        selection_layout.addLayout(select_row)
        shortcuts = QHBoxLayout()
        for label, expression in (("All", "all"), ("Odd", "odd"), ("Even", "even")):
            shortcuts.addWidget(self._action_button(label, lambda checked=False, value=expression: self._select_expression(value)))
        shortcuts.addSpacing(10)
        shortcuts.addWidget(QLabel("N"))
        self.selection_n = QSpinBox()
        self.selection_n.setRange(1, 1000000)
        self.selection_n.setValue(4)
        self.selection_n.setFixedWidth(82)
        shortcuts.addWidget(self.selection_n)
        for label, callback in (
            ("Every N", lambda: self._select_expression(f"every {self.selection_n.value()} pages")),
            ("Last N", lambda: self._select_expression(f"last {self.selection_n.value()} pages")),
            ("Invert", self._invert), ("Clear", lambda: self._select_expression(""))):
            shortcuts.addWidget(self._action_button(label, callback))
        shortcuts.addStretch(1)
        selection_layout.addLayout(shortcuts)
        self._root.addWidget(selection)

        body = QHBoxLayout()
        sidebar = QWidget()
        sidebar.setObjectName("organizerToolsPanel")
        sidebar.setFixedWidth(232)
        tools_layout = QVBoxLayout(sidebar)
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_layout.setSpacing(10)
        self._selection_buttons = []
        for heading, actions in (
            ("Arrange pages", (("Reverse", self._reverse), ("Duplicate", self._duplicate), ("Delete", self._remove_selected))),
            ("Rotate / crop", (("Rotate left", lambda: self._rotate_selected(-90)), ("Rotate right", lambda: self._rotate_selected(90)), ("Crop", self._crop))),
            ("Add / replace", (("Insert", self._insert_external), ("Blank pages", self._blank), ("Replace", self._replace_external), ("Interleave", self._interleave))),
            ("Export copies", (("Extract", self._extract_selected), ("Split", self._split))),
        ):
            group = QGroupBox(heading)
            group_layout = QGridLayout(group)
            group_layout.setSpacing(6)
            for index, (label, callback) in enumerate(actions):
                button = self._action_button(label, callback)
                group_layout.addWidget(button, index // 2, index % 2)
                if label in {"Reverse", "Duplicate", "Delete", "Rotate left", "Rotate right", "Crop", "Replace", "Extract"}:
                    self._selection_buttons.append(button)
            if heading == "Add / replace":
                self.insert_position = QComboBox()
                for label, value in (("After selection", "after"), ("Before selection", "before"), ("Beginning", "beginning"), ("End", "end")):
                    self.insert_position.addItem(label, value)
                self.insert_position.setToolTip("Insertion position for pages from another PDF")
                group_layout.addWidget(self.insert_position, 2, 0, 1, 2)
            if heading == "Export copies":
                note = QLabel("Saves new PDF files.")
                note.setToolTip("Exported PDFs remain even if you cancel this preview.")
                note.setWordWrap(True)
                note.setObjectName("secondary")
                group_layout.addWidget(note, 1, 0, 1, 2)
            tools_layout.addWidget(group)
        tools_layout.addStretch(1)
        tools_scroll = QScrollArea()
        tools_scroll.setObjectName("organizerToolsScroll")
        tools_scroll.setWidgetResizable(True)
        tools_scroll.setFrameShape(QFrame.Shape.NoFrame)
        tools_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tools_scroll.setFixedWidth(250)
        tools_scroll.setWidget(sidebar)
        body.addWidget(tools_scroll)
        preview = QVBoxLayout()
        preview_header = QHBoxLayout()
        preview_label = QLabel("PAGE PREVIEW")
        preview_label.setObjectName("secondary")
        preview_header.addWidget(preview_label)
        preview_header.addStretch(1)
        self.summary = QLabel()
        preview_header.addWidget(self.summary)
        preview.addLayout(preview_header)
        self.pages = OrganizerGrid(document)
        self.pages.orderChanged.connect(self._record_history)
        self.pages.orderChanged.connect(self._update_summary)
        self.pages.selectionChanged.connect(lambda _entries: self._update_summary())
        preview.addWidget(self.pages, 1)
        body.addLayout(preview, 1)
        self._root.addLayout(body, 1)
        self.add_validation()

        footer = QHBoxLayout()
        self.undo_plan_button = self._action_button("Undo plan", self._undo)
        self.redo_plan_button = self._action_button("Redo plan", self._redo)
        footer.addWidget(self.undo_plan_button)
        footer.addWidget(self.redo_plan_button)
        footer.addWidget(self._action_button("Restore", self._restore))
        footer.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply_button.setText("Apply Page Plan")
        self.apply_button.setObjectName("primary")
        self.apply_button.clicked.connect(self._accept_changes)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        self._root.addLayout(footer)
        self._restore()
        if preselected_pages:
            self.pages.select_source_pages(preselected_pages)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        from ui.shortcut_bindings import bind_organizer
        settings = getattr(parent, "settings", None)
        overrides = settings.get_shortcut_overrides() if settings else {}
        bind_organizer(self, {button.text(): button for button in self.findChildren(QPushButton)}, overrides)

    def _action_button(self, label, callback):
        button = QPushButton(label)
        button.setObjectName("organizerAction")
        button.setAutoDefault(False)
        def invoke():
            try:
                callback()
            except Exception as exc:
                log_failure('document_dialogs.invoke: fallback after failure', 10)
                self.show_error(f"{label} failed: {exc}")
        button.clicked.connect(invoke)
        return button

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
        snapshot = None
        confirmed = False
        try:
            with fitz.open(path) as probe:
                encrypted = probe.needs_pass
            if encrypted:
                password, accepted = QInputDialog.getText(
                    self, "Encrypted source PDF", "Password", QLineEdit.EchoMode.Password)
                if not accepted:
                    return []
            snapshot, rotations = run_job(self, "Import source PDF",
                lambda **kwargs: self.sources.snapshot(path, password, **kwargs))
            value, accepted = QInputDialog.getText(
                self, "Source pages", f"Pages (1-{len(rotations)})", text="all")
            if not accepted:
                return []
            pages = parse_page_selection(value, len(rotations))
            if not pages:
                raise ValueError("Choose at least one source page.")
            confirmed = True
            return [PagePlanEntry(uuid.uuid4().hex, "external", page, snapshot,
                                  rotations[page], password, source_label=Path(path).name)
                    for page in pages]
        except Exception as exc:
            log_failure('document_dialogs._source_entries: fallback after failure', 10)
            self.show_error(f"Cannot import source PDF: {exc}")
            return []
        finally:
            if snapshot is not None and not confirmed:
                self.sources.discard(snapshot)

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
        self._export([(Path(path), [widget.entry for widget in selected])])

    def _export(self, jobs):
        try:
            with DOCUMENT_LOCK:
                current_bytes = self.document.tobytes()
            result = run_job(self, "Export page plan", lambda **kwargs: export_plan(
                current_bytes, jobs, protected=self.protected_paths | self.sources.originals, **kwargs))
            message = f"Completed {len(result.completed)} file(s)."
            if result.completed:
                message += "\n" + "\n".join(str(path) for path in result.completed)
            if result.error:
                message += "\n" + result.error
            message += "\nExported files remain even if you cancel Organizer."
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Export result", message)
        except Exception as exc:
            log_failure('document_dialogs._export: fallback after failure', 10)
            self.show_error(f"Export failed: {exc}")

    def _split(self):
        dialog = SplitPlanDialog(self.pages.page_plan(), self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if folder:
            self._export([(Path(folder) / name, entries) for name, entries in dialog.groups])

    def _select_expression(self, expression=None):
        if not isinstance(expression, str):
            expression = self.selection_input.text()
        try:
            positions = parse_page_selection(expression, self.pages.count())
        except ValueError as exc:
            self.show_error(str(exc))
            return
        self.pages.select_positions(positions)
        self._validation.hide()

    def _invert(self):
        selected = set(self.pages.selected_positions())
        self.pages.select_positions([i for i in range(self.pages.count()) if i not in selected])

    def _reverse(self):
        self.pages.set_plan(reverse_selected(self.pages.page_plan(), self.pages.selected_positions()),
                            {w.entry.entry_id for w in self.pages.selected_widgets()})

    def _blank(self):
        positions = self.pages.selected_positions()
        reference = self.pages.page_plan()[positions[-1] if positions else -1]
        dialog = BlankPagesDialog(self.pages.reader.size(reference), self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self.pages.add_external_pages([blank_entry(*dialog.page_size()) for _ in range(dialog.count.value())],
                                          dialog.position.currentData())

    def _interleave(self):
        entries = self._source_entries()
        if entries:
            dialog = InterleaveDialog(self.pages.page_plan(), entries, self.pages.reader, self)
            if dialog.exec() == dialog.DialogCode.Accepted:
                self.pages.set_plan(dialog.plan)

    def _crop(self):
        positions = self.pages.selected_positions()
        if not positions:
            self.show_error("Select one or more pages to crop.")
            return
        dialog = CropDialog(self.pages.page_plan(), positions, self.pages.reader, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self.pages.set_plan(dialog.plan, {w.entry.entry_id for w in self.pages.selected_widgets()})

    def _record_history(self):
        if self._replaying:
            return
        plan = self.pages.page_plan()
        if self._history_index >= 0 and plan == self._history[self._history_index]:
            return
        del self._history[self._history_index + 1:]
        self._history.append(plan)
        self._history_index = len(self._history) - 1

    def _undo(self):
        self._navigate_history(-1)

    def _redo(self):
        self._navigate_history(1)

    def _navigate_history(self, step):
        index = self._history_index + step
        if not 0 <= index < len(self._history):
            return
        self._replaying = True
        try:
            self._history_index = index
            self.pages.set_plan(self._history[index])
        finally:
            self._replaying = False

    def release_sources(self):
        self.pages.reader.close()
        self.sources.close()

    def _update_summary(self) -> None:
        selected = len(self.pages.selected_widgets())
        for button in self._selection_buttons:
            button.setEnabled(selected > 0)
        self.undo_plan_button.setEnabled(self._history_index > 0)
        self.redo_plan_button.setEnabled(self._history_index < len(self._history) - 1)
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
        if self._busy:
            return
        self.pages.shutdown()
        super().done(result)
        if result != self.DialogCode.Accepted:
            self.release_sources()

    def reject(self) -> None:
        if self._busy:
            return
        self.pages.shutdown()
        super().reject()

    def closeEvent(self, event) -> None:
        if self._busy:
            event.ignore()
            return
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
