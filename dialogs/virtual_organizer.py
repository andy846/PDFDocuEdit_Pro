"""Virtual page-plan grid for large documents; native reads run off the GUI."""
from collections import OrderedDict
from dataclasses import dataclass, replace
from math import ceil

from PyQt6.QtCore import QAbstractListModel, QSize, Qt, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import QPen, QPixmap
from PyQt6.QtWidgets import QAbstractItemView, QListView, QStyledItemDelegate

from core.diagnostics import log_failure
from core.page_plan import PagePlanEntry, PlanReader, duplicate_entries
from core.pdf_engine import DOCUMENT_LOCK
from core.performance import PerformanceTrace
from core.tasks import FunctionTask, TaskCancelled

CELL_W, CELL_H = 172, 236


@dataclass(eq=False)
class PageRecord:
    entry: PagePlanEntry


class PlanModel(QAbstractListModel):
    def __init__(self, grid):
        super().__init__(grid)
        self.grid = grid

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.grid._widgets)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < self.rowCount():
            return None
        entry = self.grid._widgets[index.row()].entry
        if role == Qt.ItemDataRole.SizeHintRole:
            return QSize(CELL_W, CELL_H)
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            source = ("Blank page" if entry.source_kind == "blank" else
                      f"{entry.source_label or 'Page'} {entry.source_page + 1}")
            return f"{index.row() + 1} · {source}"

    def flags(self, index):
        return super().flags(index) | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction

    def mimeTypes(self):
        return ["application/x-pdfdocuedit-plan"]

    def mimeData(self, indexes):
        from PyQt6.QtCore import QMimeData
        data = QMimeData()
        data.setData(self.mimeTypes()[0], b"pages")
        return data


class PageDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        from PyQt6.QtWidgets import QStyle
        grid = index.model().grid
        entry = grid._widgets[index.row()].entry
        card = option.rect.adjusted(4, 4, -4, -4)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        palette = option.palette
        painter.save()
        painter.fillRect(card, palette.highlight() if selected else palette.base())
        painter.setPen(QPen(palette.mid().color()))
        painter.drawRect(card)
        painter.setPen(palette.highlightedText().color() if selected else palette.text().color())
        image_area = card.adjusted(12, 8, -12, -50)
        cached = grid._thumb_cache.get(entry)
        if cached:
            pixmap, width, height = cached
            grid._thumb_cache.move_to_end(entry)
            size = pixmap.size().scaled(image_area.size(), Qt.AspectRatioMode.KeepAspectRatio)
            x = image_area.x() + (image_area.width() - size.width()) // 2
            y = image_area.y() + (image_area.height() - size.height()) // 2
            painter.drawPixmap(x, y, size.width(), size.height(), pixmap)
            details = f"{width * 25.4 / 72:.0f} × {height * 25.4 / 72:.0f} mm · {entry.final_rotation}°"
        else:
            painter.drawText(image_area, Qt.AlignmentFlag.AlignCenter,
                             "Preview unavailable" if entry in grid._failures else "Loading…")
            details = f"{entry.final_rotation}°"
        caption = card.adjusted(6, card.height() - 46, -6, -24)
        text = painter.fontMetrics().elidedText(index.data(), Qt.TextElideMode.ElideMiddle, caption.width())
        painter.drawText(caption, Qt.AlignmentFlag.AlignCenter, text)
        painter.drawText(card.adjusted(4, card.height() - 25, -4, -3), Qt.AlignmentFlag.AlignCenter, details)
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(CELL_W, CELL_H)


class VirtualOrganizerGrid(QListView):
    orderChanged = pyqtSignal()
    planSelectionChanged = pyqtSignal(object)
    initialized = pyqtSignal()
    progress = pyqtSignal(int, int, str)
    failed = pyqtSignal(str)
    idle = pyqtSignal()

    def __init__(self, document, parent=None):
        super().__init__(parent)
        self._document = document
        self.reader = PlanReader(document)  # Explicit tools own this reader.
        self._preview_reader = PlanReader(document)  # Serial background preview worker.
        self._widgets = []  # Lightweight records, never QWidget instances.
        self._initial_plan = None
        self._thumb_cache = OrderedDict()
        self._failures = set()
        self._thumb_queue = []
        self._task = None
        self._stopping = False
        self._paused = False
        self._trace = PerformanceTrace("organizer")
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.timeout.connect(self._queue_visible)
        self._start_timer = QTimer(self)
        self._start_timer.setSingleShot(True)
        self._start_timer.timeout.connect(self._initialize)
        self.setModel(PlanModel(self))
        self.setItemDelegate(PageDelegate(self))
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setMovement(QListView.Movement.Static)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setWrapping(True)
        self.setUniformItemSizes(True)
        self.setGridSize(QSize(CELL_W, CELL_H))
        self.setSpacing(0)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.selectionModel().selectionChanged.connect(self._selection_changed)
        self.verticalScrollBar().valueChanged.connect(self._schedule_visible)

    def _selection_changed(self, *_):
        self.planSelectionChanged.emit(())

    def showEvent(self, event):
        super().showEvent(event)
        if self._initial_plan is None and self._task is None and not self._stopping:
            self._start_timer.start(0)
        self._schedule_visible()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_thumb_timer"):
            self._schedule_visible()

    def _start_task(self, function, callback):
        self._task = task = FunctionTask(function, cancel_argument="cancelled", progress_argument="progress")
        task.signals.result.connect(callback)
        task.signals.progress.connect(self.progress.emit)
        task.signals.error.connect(self.failed.emit)
        task.signals.finished.connect(self._task_finished)
        self._pool.start(task)

    def _initialize(self):
        if self._stopping or self._task is not None or self._initial_plan is not None:
            return
        document = self._document
        def prepare(cancelled, progress):
            with DOCUMENT_LOCK:
                count = document.page_count
            entries = []
            for page in range(count):
                if cancelled():
                    raise TaskCancelled
                with DOCUMENT_LOCK:
                    rotation = int(document.load_page(page).rotation)
                entries.append(PagePlanEntry(f"current-{page}", "current", page, final_rotation=rotation))
                if page % 64 == 0:
                    progress(page, count, "Preparing page plan…")
            progress(count, count, "Page plan ready")
            return entries
        self._start_task(prepare, self._prepared)

    def _prepared(self, entries):
        if self._stopping:
            return
        self._initial_plan = entries
        self.set_plan(entries)
        self._trace.mark("time_to_interactive")
        self._trace.values["page_count"] = len(entries)
        self._trace.report("interactive")
        self.initialized.emit()

    def _task_finished(self):
        self._task = None
        if self._stopping:
            self._preview_reader.close()
            self.idle.emit()
        else:
            self._schedule_visible()

    def _schedule_visible(self, *_):
        if not self._stopping:
            self._thumb_timer.start(0)

    def _visible_positions(self, overscan=0):
        if not self._widgets:
            return range(0)
        columns = max(1, self.viewport().width() // CELL_W)
        scroll = self.verticalScrollBar().value()
        first = max(0, scroll // CELL_H - overscan) * columns
        last = (ceil((scroll + self.viewport().height()) / CELL_H) + overscan) * columns
        return range(first, min(len(self._widgets), last))

    def _queue_visible(self):
        if self._stopping or self._paused or self._initial_plan is None or not self.isVisible():
            return
        visible = list(self._visible_positions())
        wanted = list(dict.fromkeys(visible + list(self._visible_positions(1))))
        self._thumb_queue = [self._widgets[row].entry for row in wanted
                             if self._widgets[row].entry not in self._thumb_cache
                             and self._widgets[row].entry not in self._failures]
        ready = sum(self._widgets[row].entry in self._thumb_cache for row in visible)
        self.progress.emit(ready, len(visible), "Loading visible previews…" if ready < len(visible) else "Previews ready")
        if self._task is not None or not self._thumb_queue:
            return
        entry = self._thumb_queue[0]
        reader = self._preview_reader
        def render(cancelled, progress):
            from .document_dialogs import _fitz_pixmap_image
            if cancelled():
                raise TaskCancelled
            try:
                with DOCUMENT_LOCK:
                    if cancelled():
                        raise TaskCancelled
                    width, height = reader.size(entry)
                    image = _fitz_pixmap_image(reader.render(entry, 160))
                return entry, image, width, height
            except TaskCancelled:
                raise
            except Exception:
                log_failure("Organizer preview render failed")
                return entry, None, 0, 0
        self._start_task(render, self._rendered)

    def _rendered(self, result):
        if self._stopping:
            return
        entry, image, width, height = result
        if image is None:
            self._failures.add(entry)
        else:
            self._thumb_cache[entry] = (QPixmap.fromImage(image), width, height)
            self._thumb_cache.move_to_end(entry)
            while len(self._thumb_cache) > 128:
                self._thumb_cache.popitem(last=False)
            if "first_preview" not in self._trace.values:
                self._trace.mark("first_preview")
                self._trace.report("first_preview")
        self.viewport().update()

    def request_stop(self):
        self._stopping = True
        self._start_timer.stop()
        self._thumb_timer.stop()
        if self._task is not None:
            self._task.cancel()
            return False
        self._preview_reader.close()
        return True

    def pause_previews(self):
        self._paused = True
        self._thumb_timer.stop()

    def resume_previews(self):
        self._paused = False
        self._schedule_visible()

    def shutdown(self):
        return self.request_stop()

    def stop_timer(self):
        self._thumb_timer.stop()

    def count(self):
        return len(self._widgets)

    def page_plan(self):
        return [record.entry for record in self._widgets]

    def order(self):
        return [record.entry.source_page for record in self._widgets]

    def rotations(self):
        return {}

    def selected_positions(self):
        return sorted(index.row() for index in self.selectedIndexes())

    def selected_widgets(self):
        return [self._widgets[row] for row in self.selected_positions()]

    def select_positions(self, positions):
        from PyQt6.QtCore import QItemSelection, QItemSelectionModel
        selection = QItemSelection()
        rows = sorted(set(row for row in positions if 0 <= row < self.count()))
        start = previous = None
        for row in rows:
            if previous is not None and row != previous + 1:
                selection.select(self.model().index(start, 0), self.model().index(previous, 0))
                start = row
            elif start is None:
                start = row
            previous = row
        if start is not None:
            selection.select(self.model().index(start, 0), self.model().index(previous, 0))
        self.selectionModel().select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def select_source_pages(self, pages):
        wanted = set(pages)
        self.select_positions(i for i, record in enumerate(self._widgets)
                              if record.entry.source_kind == "current" and record.entry.source_page in wanted)

    def set_plan(self, entries, selected_ids=None):
        if selected_ids is None:
            selected_ids = {record.entry.entry_id for record in self.selected_widgets()}
        self.model().beginResetModel()
        self._widgets = [PageRecord(entry) for entry in entries]
        self.model().endResetModel()
        self.doItemsLayout()
        self.select_positions(i for i, record in enumerate(self._widgets) if record.entry.entry_id in selected_ids)
        self.orderChanged.emit()
        self._schedule_visible()

    def restore(self):
        if self._initial_plan is not None:
            self.set_plan(self._initial_plan, set())

    def rotate_selected(self, amount):
        selected = set(self.selected_positions())
        self.set_plan([replace(record.entry, final_rotation=(record.entry.final_rotation + amount) % 360)
                       if row in selected else record.entry for row, record in enumerate(self._widgets)])

    def duplicate_selected(self):
        positions = self.selected_positions()
        if not positions:
            return False
        copies = duplicate_entries(record.entry for record in self.selected_widgets())
        plan = self.page_plan()
        plan[positions[-1]+1:positions[-1]+1] = copies
        self.set_plan(plan, {entry.entry_id for entry in copies})
        return True

    def remove_selected(self):
        positions = set(self.selected_positions())
        if self.count() - len(positions) < 1:
            return False
        self.set_plan([record.entry for row, record in enumerate(self._widgets) if row not in positions], set())
        return True

    def add_external_pages(self, entries, position="after"):
        selected = self.selected_positions()
        insertion = (0 if position == "beginning" else self.count() if position == "end" or not selected
                     else selected[0] if position == "before" else selected[-1] + 1)
        plan = self.page_plan()
        plan[insertion:insertion] = entries
        self.set_plan(plan, {entry.entry_id for entry in entries})

    def replace_selected(self, entries):
        selected = self.selected_positions()
        if not selected or not entries or selected != list(range(selected[0], selected[-1] + 1)):
            return False
        plan = self.page_plan()
        plan[selected[0]:selected[-1]+1] = entries
        self.set_plan(plan, {entry.entry_id for entry in entries})
        return True

    def dropEvent(self, event):
        if event.source() is not self:
            event.ignore()
            return
        target = self.indexAt(event.position().toPoint()).row()
        self.move_selected(self.count() if target < 0 else target)
        event.acceptProposedAction()

    def move_selected(self, target):
        selected = set(self.selected_positions())
        if not selected:
            return
        plan = self.page_plan()
        moving = [entry for i, entry in enumerate(plan) if i in selected]
        rest = [entry for i, entry in enumerate(plan) if i not in selected]
        insertion = max(0, min(len(rest), target - sum(i < target for i in selected)))
        rest[insertion:insertion] = moving
        self.set_plan(rest, {entry.entry_id for entry in moving})

    def keyPressEvent(self, event):
        control = event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
        if control and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            selected = self.selected_positions()
            if selected:
                columns = max(1, self.viewport().width() // CELL_W)
                delta = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1, Qt.Key.Key_Up: -columns, Qt.Key.Key_Down: columns}[event.key()]
                self.move_selected(selected[0] + delta if delta < 0 else selected[-1] + delta + 1)
            event.accept()
        else:
            super().keyPressEvent(event)
