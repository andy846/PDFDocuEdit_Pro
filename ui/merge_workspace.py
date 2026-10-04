"""Persistent page-aware Merge workbench; PDF viewer integration is kept in a controller."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import uuid
from bisect import bisect_right
from collections import OrderedDict, deque
from pathlib import Path

import fitz
from PyQt6.QtCore import (
    QAbstractTableModel,
    QItemSelectionModel,
    QMimeData,
    Qt,
    QThreadPool,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QAction, QColor, QImage, QKeySequence, QPainter, QPixmap, QUndoCommand, QUndoStack
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabBar,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.merge import (
    MergeItem,
    MergeSpec,
    export_merge_map,
    inspect_merge_source,
    load_merge_list,
    merge_pdf_items,
    natural_key,
    save_merge_list,
    strict_pages,
)
from core.pdf_engine import DOCUMENT_LOCK
from core.platform_service import PlatformService
from core.tasks import FunctionTask
from styles.theme import get_color

from .icons import icon


def source_key(path):
    return os.path.normcase(os.path.abspath(path))


def new_entry(path, added=0, *, label=None, snapshot=False):
    return {"id": uuid.uuid4().hex, "path": os.path.abspath(path), "label": label or Path(path).name,
            "selection": "all", "snapshot": snapshot, "added": added, "identity": {},
            "status": "Checking", "error": ""}


def render_merge_page(path, page, width, height, is_cancelled=None):
    if is_cancelled and is_cancelled():
        return None
    with DOCUMENT_LOCK, fitz.open(path) as pdf:
        current = pdf[page]
        scale = min(4096/max(current.rect.width, current.rect.height),
                    max(width/current.rect.width, height/current.rect.height, 1))
        return current.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes("png")


def capture_merge_source(engine, identity, target, is_cancelled=None):
    with DOCUMENT_LOCK:
        if identity != (engine.document_id, engine.revision) or not engine.is_loaded():
            raise ValueError("PDF changed before capture. Add its current revision again.")
        if is_cancelled and is_cancelled():
            return None
        engine.snapshot(target)
    return inspect_merge_source(target)


def scan_folder(path, recursive=False, is_cancelled=None):
    paths = []
    for root, dirs, files in os.walk(path):
        if is_cancelled and is_cancelled():
            break
        if not recursive:
            dirs[:] = []
        paths.extend(os.path.join(root, name) for name in files if name.lower().endswith(".pdf"))
    return sorted(paths, key=lambda p: natural_key(Path(p).name))


class MergeModel(QAbstractTableModel):
    HEADERS = ("Order", "PDF", "Source pages", "Selected", "Output pages", "Status")
    reorderRequested = pyqtSignal(list, int)
    filesDropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries = []
        self.output_ranges = {}

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.entries)

    def columnCount(self, parent=None):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.entries):
            return None
        entry = self.entries[index.row()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return entry["path"] + "\n" + entry.get("error", "")
        if role == Qt.ItemDataRole.DisplayRole:
            count = entry.get("identity", {}).get("pages", "—")
            selected = entry.get("selected_count", "—")
            extent = self.output_ranges.get(entry["id"], "Pending")
            return str((index.row()+1, entry["label"], count, selected, extent, entry["status"])[index.column()])

    def flags(self, index):
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsDropEnabled
        return flags | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled if index.isValid() else flags

    def mimeTypes(self):
        return ["application/x-pdfdocuedit-merge-items", "text/uri-list"]

    def mimeData(self, indexes):
        mime = QMimeData()
        rows = sorted({index.row() for index in indexes})
        mime.setData(self.mimeTypes()[0], json.dumps([self.entries[row]["id"] for row in rows]).encode())
        return mime

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction | Qt.DropAction.CopyAction

    def canDropMimeData(self, mime, action, row, column, parent):
        return mime.hasFormat(self.mimeTypes()[0]) or mime.hasUrls()

    def dropMimeData(self, mime, action, row, column, parent):
        if mime.hasFormat(self.mimeTypes()[0]):
            ids = json.loads(bytes(mime.data(self.mimeTypes()[0])))
            self.reorderRequested.emit(ids, row if row >= 0 else parent.row() if parent.isValid() else len(self.entries))
            return True
        if mime.hasUrls():
            self.filesDropped.emit([url.toLocalFile() for url in mime.urls() if url.isLocalFile()])
            return True
        return False

    def replace(self, entries):
        self.beginResetModel()
        self.entries = entries
        self.endResetModel()


class ListChange(QUndoCommand):
    def __init__(self, page, before, after, text):
        super().__init__(text)
        self.page, self.before, self.after = page, before, after

    def redo(self):
        self.page.apply_entries(copy.deepcopy(self.after))

    def undo(self):
        self.page.apply_entries(copy.deepcopy(self.before))


class PreviewView(QGraphicsView):
    zoomChanged = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.auto_fit = True
        self.fit_kind = "page"

    def show_image(self, image):
        old = self.transform()
        scroll = self.horizontalScrollBar().value(), self.verticalScrollBar().value()
        self.scene().clear()
        pixmap = QPixmap.fromImage(image)
        item = self.scene().addPixmap(pixmap)
        self.setSceneRect(item.boundingRect())
        if self.auto_fit:
            self.fit()
        else:
            self.setTransform(old)
            self.horizontalScrollBar().setValue(scroll[0])
            self.verticalScrollBar().setValue(scroll[1])

    def fit(self, kind=None):
        if kind:
            self.fit_kind = kind
        self.auto_fit = True
        rect = self.sceneRect()
        if rect.isEmpty():
            return
        self.resetTransform()
        if self.fit_kind == "width":
            scale = max(1, self.viewport().width()-12)/rect.width()
            self.scale(scale, scale)
        else:
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def zoom(self, factor):
        self.auto_fit = False
        self.scale(factor, factor)
        self.zoomChanged.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.auto_fit:
            self.fit()


class MergeWorkspace(QWidget):
    activityChanged = pyqtSignal(bool)
    titleChanged = pyqtSignal(str)

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.entries, self.list_path = [], None
        self.result = None
        self.stopped, self.closing = False, False
        self.pending_close = False
        self.capture_count = 0
        self.capture_entries = set()
        self.production_task = None
        self.busy_state = False
        self.saving = False
        self.workers = set()
        self.metadata_task = None
        self.preview_task = None
        self.pending_checks = deque()
        self.preview_generation = 0
        self.preview_cache = OrderedDict()
        self.positions = {}
        self.view_states = {}
        self.shown_entry = None
        self.directories = []
        self.model = MergeModel(self)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.undo = QUndoStack(self)
        self.undo.cleanChanged.connect(self.update_title)
        self.undo.indexChanged.connect(self.refresh_summary)
        self.actions = {}
        self.menu = QMenu("&Merge", self)
        self._build()
        self.refresh_theme()
        self.check_timer = QTimer(self)
        self.check_timer.setSingleShot(True)
        self.check_timer.timeout.connect(self.check_next)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(100)
        self.preview_timer.timeout.connect(self.request_preview)
        self.refresh_summary()

    def action(self, key, text, shortcut, callback, glyph=None):
        action = QAction(text, self)
        if glyph:
            action.setIcon(icon(glyph))
            action.setProperty("mergeIcon", glyph)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        action.triggered.connect(callback)
        self.addAction(action)
        self.menu.addAction(action)
        self.actions[key] = action
        return action

    def button(self, layout, action):
        button = QToolButton(self)
        button.setDefaultAction(action)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        layout.addWidget(button)
        return button

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)
        toolbar = QHBoxLayout()
        self.toolbar_buttons = []
        for key, text, shortcut, callback, glyph in (
            ("add", "Add PDFs", "", self.add_files, "folder-open"),
            ("folder", "Add folder", "", self.add_folder, "folder-open"),
            ("open_pdfs", "Add open PDFs", "", self.choose_open_pdfs, "file-text"),
            ("open", "Open list", "Ctrl+O", self.open_list, "folder-open"),
            ("save", "Save list", "Ctrl+S", self.save_list, "save"),
        ):
            self.toolbar_buttons.append(self.button(toolbar, self.action(key, text, shortcut, callback, glyph)))
        self.action("save_as", "Save list as…", "Ctrl+Shift+S", lambda: self.save_list(save_as=True))
        self.action("new", "New list", "Ctrl+N", self.new_list)
        self.action("close", "Close Merge", "Ctrl+W", self.request_close)
        self.action("undo", "Undo", "Ctrl+Z", self.undo.undo)
        self.action("redo", "Redo", "Ctrl+Y", self.undo.redo)
        source_button = QToolButton(self)
        source_button.setText("Review sources")
        source_button.setIcon(icon("file-text"))
        source_button.setProperty("mergeIcon", "file-text")
        source_button.setToolTip("Recheck sources, confirm changed revisions, or locate missing files")
        source_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        source_menu = QMenu(source_button)
        source_menu.addAction("Recheck selected", self.recheck_selected)
        source_menu.addAction("Confirm source / page selection", self.confirm_sources)
        source_menu.addAction("Locate file…", self.locate_source)
        source_button.setMenu(source_menu)
        source_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toolbar_buttons.append(source_button)
        toolbar.addWidget(source_button)
        toolbar.addStretch()
        root.addLayout(toolbar)
        self.splitter = QSplitter()
        self.list_panel = QWidget()
        left = QVBoxLayout(self.list_panel)
        left.setContentsMargins(0, 0, 0, 0)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.table.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.table.setDragDropOverwriteMode(False)
        self.table.setDropIndicatorShown(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col, width in ((0, 46), (2, 88), (3, 72), (4, 98), (5, 110)):
            header.resizeSection(col, width)
        self.table.selectionModel().selectionChanged.connect(self.selection_changed)
        self.table.selectionModel().currentChanged.connect(self.selection_changed)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.model.reorderRequested.connect(self.reorder)
        self.model.filesDropped.connect(self.add_paths)
        left.addWidget(self.table, 1)
        operations = QHBoxLayout()
        for key, text, shortcut, callback, glyph in (
            ("remove", "Remove", "Delete", self.remove_selected, "trash"),
            ("up", "Up", "Alt+Up", lambda: self.move(-1), "chevron-up"),
            ("down", "Down", "Alt+Down", lambda: self.move(1), "chevron-down"),
        ):
            self.button(operations, self.action(key, text, shortcut, callback, glyph))
        self.action("duplicate", "Duplicate entry", "Ctrl+D", self.duplicate)
        self.action("top", "Move to top", "", lambda: self.reorder(self.selected_ids(), 0))
        self.action("bottom", "Move to bottom", "", lambda: self.reorder(self.selected_ids(), len(self.entries)))
        sort_button = QToolButton()
        sort_button.setText("Sort")
        sort_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        sort_menu = QMenu(sort_button)
        for label, value in (("Filename natural order", "name"), ("Added order", "added"), ("Reverse order", "reverse")):
            sort_menu.addAction(label, lambda checked=False, mode=value: self.sort_entries(mode))
        sort_button.setMenu(sort_menu)
        operations.addWidget(sort_button)
        operations.addStretch()
        left.addLayout(operations)
        self.empty_hint = QLabel("Drop PDFs here, add a folder, or choose open documents. Drag rows to arrange the merge order.")
        self.empty_hint.setWordWrap(True)
        left.addWidget(self.empty_hint)
        self.preview_panel = QWidget()
        right = QVBoxLayout(self.preview_panel)
        right.setContentsMargins(0, 0, 0, 0)
        nav = QHBoxLayout()
        self.preview_mode = QComboBox()
        self.preview_mode.setMaximumWidth(130)
        self.preview_mode.addItems(["Source", "Merge order"])
        self.preview_mode.currentIndexChanged.connect(self.preview_mode_changed)
        nav.addWidget(self.preview_mode)
        previous = QToolButton()
        previous.setIcon(icon("chevron-left"))
        previous.setProperty("mergeIcon", "chevron-left")
        previous.setToolTip("Previous page")
        previous.clicked.connect(lambda: self.page_number.setValue(self.page_number.value()-1))
        nav.addWidget(previous)
        self.page_number = QSpinBox()
        self.page_number.setFixedWidth(115)
        self.page_number.setStyleSheet("QSpinBox { padding: 4px 42px 4px 6px; }")
        self.page_number.setMinimum(1)
        self.page_number.valueChanged.connect(self.schedule_preview)
        nav.addWidget(self.page_number)
        self.page_total = QLabel("/ 0")
        nav.addWidget(self.page_total)
        next_button = QToolButton()
        next_button.setIcon(icon("chevron-right"))
        next_button.setProperty("mergeIcon", "chevron-right")
        next_button.setToolTip("Next page")
        next_button.clicked.connect(lambda: self.page_number.setValue(self.page_number.value()+1))
        nav.addWidget(next_button)
        right.addLayout(nav)
        self.preview_label = QLabel("Select a PDF to preview")
        self.preview_label.setWordWrap(True)
        self.preview_label.setTextFormat(Qt.TextFormat.PlainText)
        right.addWidget(self.preview_label)
        self.preview = PreviewView()
        self.preview.setMinimumHeight(145)
        right.addWidget(self.preview, 1)
        nav.addStretch()
        for text, callback in (("Fit page", lambda: self.preview.fit("page")), ("Fit width", lambda: self.preview.fit("width")),
                               ("−", lambda: self.preview.zoom(.8)), ("+", lambda: self.preview.zoom(1.25))):
            button = QToolButton()
            button.setText(text)
            button.clicked.connect(callback)
            nav.addWidget(button)
        selection = QHBoxLayout()
        self.range_mode = QComboBox()
        self.range_mode.addItems(["All pages", "Custom range", "Odd pages", "Even pages"])
        self.range_edit = QLineEdit()
        self.range_edit.setPlaceholderText("1,3,5-8")
        self.range_edit.setMinimumWidth(75)
        self.range_mode.currentIndexChanged.connect(lambda: self.range_edit.setEnabled(self.range_mode.currentIndex() == 1))
        self.range_edit.setEnabled(False)
        self.apply_range = QPushButton("Apply")
        self.apply_range.setToolTip("Apply to all selected PDF entries")
        self.apply_range.clicked.connect(self.apply_selection)
        selection.addWidget(self.range_mode)
        selection.addWidget(self.range_edit, 1)
        selection.addWidget(self.apply_range)
        right.addLayout(selection)
        self.selection_info = QLabel()
        self.selection_info.setWordWrap(True)
        right.addWidget(self.selection_info)
        self.splitter.addWidget(self.list_panel)
        self.splitter.addWidget(self.preview_panel)
        self.splitter.setSizes([600, 380])
        self.narrow_tabs = QTabBar()
        self.narrow_tabs.addTab("Files")
        self.narrow_tabs.addTab("Preview & pages")
        self.narrow_tabs.currentChanged.connect(self.switch_narrow)
        self.narrow_tabs.hide()
        root.addWidget(self.narrow_tabs)
        root.addWidget(self.splitter, 1)
        output = QHBoxLayout()
        output.addWidget(QLabel("Output"))
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Choose merged PDF destination…")
        self.output_edit.textChanged.connect(self.options_changed)
        output.addWidget(self.output_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.choose_output)
        output.addWidget(browse)
        root.addLayout(output)
        self.compact = QCheckBox("Deep compression (slower; output may not become smaller)")
        self.compact.toggled.connect(self.options_changed)
        advanced = QToolButton()
        advanced.setText("Output options")
        advanced.setCheckable(True)
        advanced.toggled.connect(self.compact.setVisible)
        self.compact.hide()
        output.addWidget(advanced)
        root.addWidget(self.compact)
        footer = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        footer.addWidget(self.summary, 1)
        self.generate_button = QPushButton("Merge PDFs")
        self.generate_button.setProperty("primary", True)
        self.generate_button.clicked.connect(self.generate)
        footer.addWidget(self.generate_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_job)
        self.cancel_button.hide()
        footer.addWidget(self.cancel_button)
        root.addLayout(footer)
        self.progress = QProgressBar()
        self.progress.hide()
        root.addWidget(self.progress)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.message)
        self.results_row = QWidget()
        results = QGridLayout(self.results_row)
        self.results_layout = results
        results.setContentsMargins(0, 0, 0, 0)
        self.result_buttons = []
        for text, callback in (("Open merged PDF", self.open_output), ("Send to Designer", self.send_output),
                               ("Show in folder", self.reveal_output), ("Export page map", self.export_map),
                               ("Merge again", self.generate)):
            button = QToolButton()
            button.setText(text)
            button.clicked.connect(callback)
            results.addWidget(button, 0, len(self.result_buttons))
            self.result_buttons.append(button)
        self.result_buttons[1].setVisible(getattr(self.window, "_mode_controller", None) is not None)
        self.results_row.hide()
        root.addWidget(self.results_row)

    def update_title(self, *_):
        name = self.list_path.name if self.list_path else "Merge PDFs"
        self.titleChanged.emit(name + (" *" if not self.undo.isClean() else "") + (" · Running" if self.production_task else ""))

    def refresh_theme(self):
        self.table.setStyleSheet("QTableView::item:selected { background: " + get_color("primary")
                                + "; color: " + get_color("on_primary") + "; }")
        self.preview.setBackgroundBrush(QColor(get_color("canvas")))
        for action in self.actions.values():
            if action.property("mergeIcon"):
                action.setIcon(icon(action.property("mergeIcon")))
        for button in self.findChildren(QToolButton):
            if button.property("mergeIcon"):
                button.setIcon(icon(button.property("mergeIcon")))

    def options_changed(self, *_):
        if not getattr(self, "_loading_options", False):
            self.undo.resetClean()
        self.refresh_summary()

    def selected_ids(self):
        return [self.entries[index.row()]["id"] for index in self.table.selectionModel().selectedRows()]

    def commit(self, after, text):
        if self.busy_state or self.saving or self.stopped:
            return
        if self.entries != after:
            self.undo.push(ListChange(self, copy.deepcopy(self.entries), after, text))

    def apply_entries(self, entries):
        selected = set(self.selected_ids())
        current = self.current_entry()
        focused_id = current["id"] if current else None
        # New metadata supersedes cached command snapshots after undo/redo.
        current = {entry["id"]: entry for entry in self.entries}
        for entry in entries:
            if entry["id"] in current and entry["path"] == current[entry["id"]]["path"]:
                for key in ("identity", "status", "error", "review_required"):
                    if key in current[entry["id"]]:
                        entry[key] = copy.deepcopy(current[entry["id"]][key])
            elif entry["id"] not in self.capture_entries and entry["status"] != "Capturing":
                entry["status"] = "Checking"
            if entry["status"] == "Capturing" and entry["id"] not in self.capture_entries:
                entry["status"] = "Checking"
        self.entries = entries
        self.model.replace(entries)
        selection = self.table.selectionModel()
        for row, entry in enumerate(entries):
            if entry["id"] in selected:
                selection.select(self.model.index(row, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
            if entry["id"] == focused_id:
                selection.setCurrentIndex(self.model.index(row, 0), QItemSelectionModel.SelectionFlag.NoUpdate)
        self.refresh_summary()
        self.queue_checks()
        self.selection_changed()

    def queue_checks(self, force=False):
        queued = {item["id"] for item in self.pending_checks}
        if self.metadata_task:
            queued.add(self.metadata_task.entry_id)
        for entry in self.entries:
            if (force or entry["status"] == "Checking") and entry["id"] not in queued:
                entry["status"] = "Checking"
                self.pending_checks.append(copy.deepcopy(entry))
        self.check_timer.start(0)

    def launch(self, function, *args, ready=None, failed=None, finished=None, **kwargs):
        task = FunctionTask(function, *args, **kwargs)
        self.workers.add(task)
        if ready:
            def received(result):
                if self.stopped:
                    return
                try:
                    ready(result)
                except Exception as error:
                    (failed or self.error)(str(error))
            task.signals.result.connect(received)
        task.signals.error.connect(lambda error: (failed or self.error)(error) if not self.stopped else None)
        def ended():
            self.workers.discard(task)
            if finished:
                finished()
            if self.stopped and not self.workers:
                self.cleanup()
        task.signals.finished.connect(ended)
        self.pool.start(task)
        return task

    def check_next(self):
        if self.stopped or self.metadata_task:
            return
        while self.pending_checks:
            entry = self.pending_checks.popleft()
            if any(e["id"] == entry["id"] and e["path"] == entry["path"] for e in self.entries):
                break
        else:
            return
        def inspect():
            identity = inspect_merge_source(entry["path"])
            if entry.get("digest"):
                import hashlib
                with open(entry["path"], "rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != entry["digest"]:
                        raise ValueError("Saved snapshot digest mismatch. Restore the original assets.")
            return identity
        def ready(identity):
            self.source_checked(entry, identity)
        def failed(error):
            self.source_checked(entry, None, error)
        def finished():
            self.metadata_task = None
            self.check_timer.start(0)
        self.metadata_task = self.launch(inspect, ready=ready, failed=failed, finished=finished)
        self.metadata_task.entry_id = entry["id"]

    def source_checked(self, requested, identity, error=""):
        for entry in self.entries:
            if entry["id"] != requested["id"] or entry["path"] != requested["path"]:
                continue
            old = entry.get("identity", {})
            changed = bool(old and identity and any(old.get(k) != identity[k] for k in ("size", "mtime_ns", "pages")))
            entry["review_required"] = bool(entry.get("review_required") or changed)
            entry["status"] = "Unavailable" if error else "Needs review" if entry["review_required"] else "Ready"
            entry["error"] = error or ("Source changed. Review pages and choose Confirm source." if entry["review_required"] else "")
            if identity:
                entry["identity"] = identity
            self.refresh_summary()
            self.selection_changed()
            break

    def refresh_summary(self, *_):
        total, blocked, known = 0, 0, True
        self.ends = []
        self.model.output_ranges = {}
        for entry in self.entries:
            entry.pop("selected_count", None)
            entry.pop("selection_error", None)
            try:
                if entry["status"] != "Ready":
                    raise ValueError(entry["error"])
                pages = strict_pages(entry["selection"], entry["identity"]["pages"])
                entry["selected_count"] = len(pages)
                if known:
                    self.model.output_ranges[entry["id"]] = f"{total+1}–{total+len(pages)}"
                total += len(pages)
            except Exception as error:
                if entry["status"] == "Ready":
                    entry["selection_error"] = str(error)
                blocked += 1
                known = False
            self.ends.append(total)
        self.total_pages = total
        self.summary.setText(f"{len(self.entries):,} PDFs · {total:,} selected pages" + (f" · {blocked} need attention" if blocked else ""))
        self.generate_button.setEnabled(bool(self.entries) and not blocked and not self.busy_state and not self.saving and not self.stopped)
        self.empty_hint.setVisible(not self.entries)
        self.actions["undo"].setEnabled(self.undo.canUndo() and not self.production_task)
        self.actions["redo"].setEnabled(self.undo.canRedo() and not self.production_task)
        if self.entries:
            self.model.dataChanged.emit(self.model.index(0, 0), self.model.index(len(self.entries)-1, 5))
        self.update_title()

    def add_paths(self, paths):
        if self.busy_state or self.saving or self.stopped:
            return
        known = {source_key(entry["path"]) for entry in self.entries}
        additions, skipped = [], 0
        added = max((e["added"] for e in self.entries), default=-1)+1
        for path in sorted(paths, key=lambda p: natural_key(Path(p).name)):
            if Path(path).suffix.casefold() != ".pdf":
                skipped += 1
                continue
            key = source_key(path)
            if key in known:
                skipped += 1
                continue
            known.add(key)
            additions.append(new_entry(path, added+len(additions)))
        self.commit(copy.deepcopy(self.entries)+additions, "Add PDFs")
        if skipped:
            self.error(f"Skipped {skipped} duplicate or non-PDF file(s). Use Duplicate entry to repeat a source.")

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add PDFs", "", "PDF (*.pdf)")
        self.add_paths(paths)

    def add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Add PDF folder")
        if not path:
            return
        recursive = QMessageBox.question(self, "Subfolders", "Include PDFs in subfolders?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
        self.launch(scan_folder, path, recursive, ready=self.add_paths, cancel_argument="is_cancelled")

    def choose_open_pdfs(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Add open PDFs — capture current edits")
        layout = QVBoxLayout(dialog)
        choices = QListWidget()
        sessions = [s for s in self.window._sessions if s.engine.is_loaded()]
        for session in sessions:
            item = QListWidgetItem(session.document_name + (" · Unsaved edits" if session.engine.is_modified else ""))
            item.setCheckState(Qt.CheckState.Unchecked)
            choices.addItem(item)
        layout.addWidget(choices)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            chosen = [s for i, s in enumerate(sessions) if choices.item(i).checkState() == Qt.CheckState.Checked]
            for session in sorted(chosen, key=lambda s: natural_key(s.document_name)):
                self.add_session(session)

    def add_session(self, session):
        if self.busy_state or self.saving:
            return
        if session.form_draft and session.form_draft.changed:
            prompt = QMessageBox(self)
            prompt.setWindowTitle("Unapplied form draft")
            prompt.setText("Apply the form draft before capturing this PDF?")
            apply = prompt.addButton("Apply", QMessageBox.ButtonRole.AcceptRole)
            ignore = prompt.addButton("Send without draft", QMessageBox.ButtonRole.ActionRole)
            prompt.addButton(QMessageBox.StandardButton.Cancel)
            prompt.exec()
            if prompt.clickedButton() is apply:
                self.window.workspace.set_current_session(session)
                if not self.window._apply_form_draft():
                    return
            elif prompt.clickedButton() is not ignore:
                return
        identity = (session.engine.document_id, session.engine.revision)
        label = session.document_name
        if any(entry.get("session_identity") == list(identity) for entry in self.entries):
            self.error("This document revision is already listed. Use Duplicate entry to repeat it.")
            return
        directory = tempfile.TemporaryDirectory(prefix="pdfdocuedit-merge-")
        self.directories.append(directory)
        path = str(Path(directory.name)/"snapshot.pdf")
        entry = new_entry(path, max((e["added"] for e in self.entries), default=-1)+1, label=label, snapshot=True)
        entry["session_identity"] = list(identity)
        entry["original_path"] = str(session.display_path or session.engine.original_path or "")
        entry["status"] = "Capturing"
        self.capture_entries.add(entry["id"])
        self.commit(copy.deepcopy(self.entries)+[entry], "Add open PDF")
        self.capture_count += 1
        mode = getattr(self.window, "_mode_controller", None)
        pdf_mode = mode.modes.pages["pdf"] if mode else self.window.splitter
        if self.capture_count == 1:
            self.capture_pdf_enabled = pdf_mode.isEnabled()
            pdf_mode.setEnabled(False)
        session.tab_widget.setEnabled(False)
        def ready(detail):
            self.source_checked(entry, detail)
        def finished():
            self.capture_count -= 1
            if self.capture_count == 0:
                pdf_mode.setEnabled(self.capture_pdf_enabled)
            self.capture_entries.discard(entry["id"])
            for current in self.entries:
                if current["id"] == entry["id"] and current["status"] == "Capturing":
                    current["status"] = "Checking"
                    self.queue_checks()
            if session in self.window._sessions:
                session.tab_widget.setEnabled(True)
        self.launch(capture_merge_source, session.engine, identity, path, ready=ready,
                    failed=lambda error: self.source_checked(entry, None, error), finished=finished, cancel_argument="is_cancelled")

    def remove_selected(self):
        ids = set(self.selected_ids())
        self.commit([copy.deepcopy(e) for e in self.entries if e["id"] not in ids], "Remove PDFs")

    def duplicate(self):
        ids = set(self.selected_ids())
        after = []
        for entry in self.entries:
            after.append(copy.deepcopy(entry))
            if entry["id"] in ids:
                duplicate = copy.deepcopy(entry)
                duplicate["id"] = uuid.uuid4().hex
                duplicate["added"] = max((e["added"] for e in self.entries), default=0)+len(after)
                after.append(duplicate)
        self.commit(after, "Duplicate PDFs")

    def reorder(self, ids, target):
        ids = set(ids)
        selected = [copy.deepcopy(e) for e in self.entries if e["id"] in ids]
        target -= sum(e["id"] in ids for e in self.entries[:target])
        remaining = [copy.deepcopy(e) for e in self.entries if e["id"] not in ids]
        target = max(0, min(target, len(remaining)))
        self.commit(remaining[:target]+selected+remaining[target:], "Move PDFs")

    def move(self, offset):
        ids = set(self.selected_ids())
        after = copy.deepcopy(self.entries)
        sequence = range(1, len(after)) if offset < 0 else range(len(after)-2, -1, -1)
        for i in sequence:
            other = i+offset
            if after[i]["id"] in ids and after[other]["id"] not in ids:
                after[i], after[other] = after[other], after[i]
        self.commit(after, "Move PDFs")

    def sort_entries(self, mode):
        after = copy.deepcopy(self.entries)
        if mode == "reverse":
            after.reverse()
        else:
            after.sort(key=lambda e: natural_key(e["label"]) if mode == "name" else e["added"])
        self.commit(after, "Sort PDFs")

    def apply_selection(self):
        ids = set(self.selected_ids())
        if not ids:
            return
        value = ["all", self.range_edit.text(), "odd", "even"][self.range_mode.currentIndex()]
        try:
            for entry in self.entries:
                if entry["id"] in ids:
                    if entry["status"] not in ("Ready", "Needs review"):
                        raise ValueError("Check and confirm all selected sources first.")
                    strict_pages(value, entry["identity"]["pages"])
            after = copy.deepcopy(self.entries)
            for entry in after:
                if entry["id"] in ids:
                    entry["selection"] = value.strip()
            self.commit(after, "Change selected pages")
            self.selection_info.setText("Page selection updated")
            self.schedule_preview()
        except Exception as error:
            self.selection_info.setText(str(error))

    def show_context_menu(self, point):
        menu = QMenu(self)
        for key in ("up", "down", "top", "bottom", "duplicate", "remove"):
            menu.addAction(self.actions[key])
        menu.addSeparator()
        menu.addAction("Recheck source", lambda: self.recheck_selected())
        menu.addAction("Confirm source / page selection", self.confirm_sources)
        menu.addAction("Locate file…", self.locate_source)
        menu.exec(self.table.viewport().mapToGlobal(point))

    def recheck_selected(self):
        if self.busy_state or self.saving or self.stopped:
            return
        ids = set(self.selected_ids())
        for entry in self.entries:
            if entry["id"] in ids:
                entry["status"] = "Checking"
        self.queue_checks()
        self.refresh_summary()

    def confirm_sources(self):
        if self.busy_state or self.saving or self.stopped:
            return
        ids = set(self.selected_ids())
        for entry in self.entries:
            if entry["id"] in ids and entry["status"] == "Needs review":
                try:
                    strict_pages(entry["selection"], entry["identity"]["pages"])
                except Exception as error:
                    self.error(str(error)+" Choose All pages or correct the custom range, then confirm again.")
                    return
        if QMessageBox.question(self, "Confirm sources", "Use the checked source revisions and selected pages?") != QMessageBox.StandardButton.Yes:
            return
        for entry in self.entries:
            if entry["id"] in ids and entry["status"] == "Needs review":
                entry["status"], entry["error"] = "Ready", ""
                entry["review_required"] = False
        self.undo.resetClean()
        self.refresh_summary()
        self.schedule_preview()

    def locate_source(self):
        if self.busy_state or self.saving or self.stopped:
            return
        ids = self.selected_ids()
        if len(ids) != 1:
            self.error("Select one missing source to locate.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Locate PDF", "", "PDF (*.pdf)")
        if path:
            after = copy.deepcopy(self.entries)
            entry = next(e for e in after if e["id"] == ids[0])
            entry.update(path=os.path.abspath(path), status="Checking", error="", snapshot=False)
            entry.pop("digest", None)
            self.commit(after, "Locate PDF source")

    def selection_changed(self, *_):
        ids = self.selected_ids()
        self.apply_range.setEnabled(bool(ids) and not self.production_task)
        for key in ("remove", "up", "down", "duplicate", "top", "bottom"):
            self.actions[key].setEnabled(bool(ids) and not self.production_task)
        if len(ids) == 1:
            entry = next(e for e in self.entries if e["id"] == ids[0])
            self.selection_info.setText(entry.get("error", "") or entry.get("selection_error", ""))
            value = entry["selection"].casefold()
            self.range_mode.setCurrentIndex({"all": 0, "odd": 2, "even": 3}.get(value, 1))
            self.range_edit.setText("" if value in ("all", "odd", "even") else value)
        self.preview_mode_changed()

    def preview_mode_changed(self, *_):
        count = 0
        entry = self.current_entry()
        if self.preview_mode.currentIndex() == 1:
            count = self.total_pages if all(e["status"] == "Ready" for e in self.entries) else 0
        elif entry:
            count = entry.get("identity", {}).get("pages", 0)
        self.page_number.blockSignals(True)
        self.page_number.setMaximum(max(1, count))
        if entry and self.preview_mode.currentIndex() == 0:
            self.page_number.setValue(min(max(1, count), self.positions.get(entry["id"], 1)))
        self.page_number.blockSignals(False)
        self.page_number.setEnabled(bool(count))
        self.page_total.setText(f"/ {count:,}")
        self.schedule_preview()

    def current_entry(self):
        index = self.table.currentIndex()
        return self.entries[index.row()] if index.isValid() and index.row() < len(self.entries) else None

    def preview_source(self):
        if self.preview_mode.currentIndex() == 1:
            if not self.entries or not self.total_pages or any(e["status"] != "Ready" for e in self.entries):
                return None
            number = self.page_number.value()-1
            index = bisect_right(self.ends, number)
            entry = self.entries[index]
            offset = number-(self.ends[index-1] if index else 0)
            return entry, strict_pages(entry["selection"], entry["identity"]["pages"])[offset]
        entry = self.current_entry()
        if not entry or entry["status"] not in ("Ready", "Needs review"):
            return None
        page = self.page_number.value()-1
        self.positions[entry["id"]] = page+1
        return entry, page

    def schedule_preview(self, *_):
        if hasattr(self, "preview_timer") and not self.stopped:
            self.preview_generation += 1
            self.preview_timer.start()

    def request_preview(self):
        if self.stopped:
            return
        generation = self.preview_generation
        try:
            source = self.preview_source()
        except Exception as error:
            self.error(str(error))
            return
        if not source:
            self.preview_label.setText("Select a checked source to preview")
            self.preview.scene().clear()
            return
        entry, page = source
        if self.shown_entry and self.shown_entry != entry["id"]:
            self.view_states[self.shown_entry] = (self.preview.transform(), self.preview.auto_fit,
                self.preview.fit_kind, self.preview.horizontalScrollBar().value(), self.preview.verticalScrollBar().value())
        try:
            selected = page in strict_pages(entry["selection"], entry["identity"]["pages"])
        except Exception:
            selected = False
        self.preview_label.setText(f"{entry['label']} · Source page {page+1}" +
            (f" · Output page {self.page_number.value()}" if self.preview_mode.currentIndex() == 1 else " · Included" if selected else " · Excluded"))
        width = max(400, int(self.preview.viewport().width()*self.devicePixelRatioF()))
        height = max(600, int(self.preview.viewport().height()*self.devicePixelRatioF()))
        key = (entry["path"], entry["identity"].get("mtime_ns"), page, width, height)
        if key in self.preview_cache:
            self.preview_cache.move_to_end(key)
            self.show_preview_image(entry["id"], self.preview_cache[key])
            return
        if self.preview_task:
            self.preview_task.cancel()
            self.preview_timer.start(150)
            return
        def ready(data):
            if generation != self.preview_generation or data is None:
                return
            image = QImage.fromData(data)
            if image.isNull():
                raise ValueError("Unable to decode PDF preview.")
            self.preview_cache[key] = image
            while len(self.preview_cache) > 6:
                self.preview_cache.popitem(last=False)
            self.show_preview_image(entry["id"], image)
        def finished():
            self.preview_task = None
        self.preview_task = self.launch(render_merge_page, entry["path"], page, width, height,
            ready=ready, failed=lambda error: self.error(error) if generation == self.preview_generation else None,
            finished=finished, cancel_argument="is_cancelled")

    def show_preview_image(self, entry_id, image):
        changed = self.shown_entry != entry_id
        state = self.view_states.get(entry_id) if changed else None
        if state:
            self.preview.setTransform(state[0])
            self.preview.auto_fit, self.preview.fit_kind = state[1], state[2]
        elif changed:
            self.preview.auto_fit = True
            self.preview.fit_kind = "page"
        self.preview.show_image(image)
        if state and not state[1]:
            self.preview.horizontalScrollBar().setValue(state[3])
            self.preview.verticalScrollBar().setValue(state[4])
        self.shown_entry = entry_id

    def choose_output(self):
        path, _ = QFileDialog.getSaveFileName(self, "Merged PDF destination", self.output_edit.text() or "merged.pdf", "PDF (*.pdf)")
        if path:
            self.output_edit.setText(path if path.lower().endswith(".pdf") else path+".pdf")

    def generate(self):
        if self.busy_state or self.saving or self.stopped:
            return
        self.refresh_summary()
        if not self.generate_button.isEnabled():
            self.error("Check and resolve all sources and page selections first.")
            return
        if not self.output_edit.text().strip():
            self.choose_output()
        if not self.output_edit.text().strip():
            return
        target = Path(self.output_edit.text()).expanduser()
        if target.suffix.casefold() != ".pdf":
            self.error("Choose an output filename ending in .pdf.")
            return
        protected = [str(s.display_path or s.engine.original_path) for s in self.window._sessions
                     if s.display_path or s.engine.original_path]
        protected += [e.get("original_path", "") for e in self.entries if e.get("original_path")]
        if source_key(str(target)) in {source_key(p) for p in protected+[e["path"] for e in self.entries]}:
            self.error("Output cannot replace a source or an open PDF.")
            return
        items = [MergeItem(e["path"], strict_pages(e["selection"], e["identity"]["pages"]), e["id"],
                           copy.deepcopy(e["identity"]), e["label"]) for e in self.entries]
        spec = MergeSpec(items, str(target), self.compact.isChecked(), protected)
        self.result = None
        self.results_row.hide()
        self.error("Checking sources and output destination…")
        def run(progress=None, is_cancelled=None):
            return merge_pdf_items(spec, progress, is_cancelled)
        # Existing output check is background; GUI never stats a disconnected UNC.
        def checked(exists):
            if exists and QMessageBox.question(self, "Replace output", "Replace the existing output PDF?\nSources will remain unchanged.") != QMessageBox.StandardButton.Yes:
                self.production_task = None
                self.set_busy(False)
                return
            self.production_task = self.launch(run, ready=self.generated, finished=self.production_finished,
                progress_argument="progress", cancel_argument="is_cancelled")
            self.production_task.signals.progress.connect(self.show_progress)
            self.production_task.signals.cancelled.connect(lambda: self.error("Cancelled. Merge list retained; no new output published."))
        self.set_busy(True)
        def precheck_finished():
            if self.production_task is precheck:
                self.production_finished()
        precheck = self.launch(target.exists, ready=checked, failed=self.error, finished=precheck_finished)
        self.production_task = precheck

    def show_progress(self, done, total, message):
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.error(message)

    def generated(self, result):
        self.result = result
        self.results_row.show()
        self.error(f"Merged {len(self.entries)} PDFs · {result.page_count:,} pages" +
                   (f" · {len(result.warnings)} warning(s) — see tooltip" if result.warnings else ""))
        self.message.setToolTip(str(result.output_path)+"\n"+"\n".join(result.warnings))

    def production_finished(self):
        self.production_task = None
        self.set_busy(False)
        if self.pending_close:
            self.request_close()

    def set_busy(self, busy):
        self.busy_state = busy
        self.table.setEnabled(not busy)
        self.list_panel.setEnabled(not busy)
        for button in self.toolbar_buttons:
            button.setEnabled(not busy)
        self.output_edit.setEnabled(not busy)
        self.compact.setEnabled(not busy)
        self.range_mode.setEnabled(not busy)
        self.range_edit.setEnabled(not busy and self.range_mode.currentIndex() == 1)
        self.progress.setVisible(busy)
        self.cancel_button.setVisible(busy)
        for action in self.actions.values():
            action.setEnabled(not busy or action is self.actions["close"])
        self.activityChanged.emit(busy)
        self.refresh_summary()
        self.generate_button.setEnabled(self.generate_button.isEnabled() and not busy)
        self.apply_range.setEnabled(not busy and bool(self.selected_ids()))

    def cancel_job(self):
        if self.production_task:
            self.production_task.cancel()

    def error(self, message):
        self.message.setText(str(message))

    def open_output(self):
        if self.result:
            self.window.queue_open_files([str(self.result.output_path)])

    def send_output(self):
        if self.result:
            def opened(session):
                def transfer():
                    if session not in self.window._sessions or self.stopped:
                        return
                    if self.window._tasks:
                        QTimer.singleShot(100, transfer)
                        return
                    self.window._mode_controller.handoff.choose_project(session)
                QTimer.singleShot(0, transfer)
            self.window.open_in_new_tab(str(self.result.output_path), on_open=opened)

    def reveal_output(self):
        if self.result:
            PlatformService.open_folder(self.result.output_path.parent)

    def export_map(self):
        if not self.result:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export source page map", "merge-pages.csv", "CSV (*.csv)")
        if path:
            self.launch(export_merge_map, self.result, path, ready=lambda _: self.error("Source page map exported."))

    def save_list(self, checked=False, *, save_as=False, path=None, allow_busy=False):
        if (self.busy_state and not allow_busy) or self.saving:
            return False
        if path is None:
            path = None if save_as else self.list_path
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Save merge list", "merge.pdmerge", "Merge list (*.pdmerge)")
        if not path:
            return False
        path = Path(path)
        if path.suffix.casefold() != ".pdmerge":
            path = Path(str(path)+".pdmerge")
        if any(e["snapshot"] and e["status"] != "Ready" for e in self.entries):
            self.error("Finish capturing/checking snapshot sources before saving.")
            return False
        # Run asset copy/save off the GUI; closing after Save completes via request_close.
        state = copy.deepcopy(self.entries)
        index = self.undo.index()
        output, compact = self.output_edit.text(), self.compact.isChecked()
        self.saving = True
        self.activityChanged.emit(self.busy_state)
        def ready(saved):
            self.list_path = saved
            if index == self.undo.index() and state == self.entries and output == self.output_edit.text() and compact == self.compact.isChecked():
                self.undo.setClean()
            self.error(f"Merge list saved: {saved.name}")
        def finished():
            self.saving = False
            self.activityChanged.emit(self.busy_state)
            callback = getattr(self, "_after_save", None)
            self._after_save = None
            if callback and self.undo.isClean():
                QTimer.singleShot(0, callback)
        self.launch(save_merge_list, path, state, output, compact, ready=ready, finished=finished)
        return True

    def confirm_discard(self, after_save=None):
        if self.saving:
            self.error("Wait for the merge list to finish saving.")
            return False
        if self.undo.isClean():
            return True
        answer = QMessageBox.question(self, "Unsaved merge list", "Save the merge list before closing?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Discard:
            return True
        if answer == QMessageBox.StandardButton.Save:
            if self.save_list(allow_busy=True):
                self._after_save = after_save
        return False

    def new_list(self):
        if self.busy_state or self.saving:
            return
        if not self.confirm_discard(after_save=self.new_list):
            return
        self.list_path = None
        self.apply_entries([])
        self.undo.clear()
        self.undo.setClean()
        self.result = None
        self.results_row.hide()

    def open_list(self, checked=False, *, path=None):
        if self.busy_state or self.saving:
            return
        if not self.confirm_discard(after_save=lambda: self.open_list(path=path)):
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open merge list", "", "Merge list (*.pdmerge)")
        if not path:
            return
        def ready(raw):
            self.list_path = Path(path)
            self.entries = []
            self.apply_entries(raw["items"])
            self._loading_options = True
            self.output_edit.setText(raw["output_path"])
            self.compact.setChecked(raw["compact"])
            self._loading_options = False
            self.undo.clear()
            self.undo.setClean()
            self.result = None
            self.results_row.hide()
        self.set_busy(True)
        self.production_task = self.launch(load_merge_list, path, ready=ready, finished=self.production_finished)

    def request_close(self):
        if self.production_task:
            answer = QMessageBox.question(self, "Merge running", "Cancel the merge job and close this tab?\nChoose No to keep it running.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                self.pending_close = True
                self.production_task.cancel()
            return
        if getattr(self, "saving", False):
            self.error("Wait for the merge list to finish saving.")
            return
        if not self.confirm_discard(after_save=self.request_close):
            return
        self.stop()
        self.window.workspace.remove_tool_tab(self)
        self.window._merge_workspace = None

    def stop(self):
        self.stopped = True
        self.check_timer.stop()
        self.preview_timer.stop()
        self.pending_checks.clear()
        for worker in list(self.workers):
            worker.cancel()
        if not self.workers:
            self.cleanup()

    def cleanup(self):
        for directory in self.directories:
            directory.cleanup()
        self.directories.clear()
        self.preview_cache.clear()

    def switch_narrow(self, index):
        if self.narrow_tabs.isVisible():
            self.list_panel.setVisible(index == 0)
            self.preview_panel.setVisible(index == 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        narrow = self.width() < 1000
        self.narrow_tabs.setVisible(narrow)
        self.list_panel.setVisible(not narrow or self.narrow_tabs.currentIndex() == 0)
        self.preview_panel.setVisible(not narrow or self.narrow_tabs.currentIndex() == 1)
        for button in self.toolbar_buttons:
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly if self.width() < 650 else Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for index, width in ((0, 65), (2, 110), (3, 85), (4, 110), (5, 100)):
            self.table.horizontalHeader().resizeSection(index, width)
        columns = 2 if self.width() < 650 else 5
        for i, button in enumerate(self.result_buttons):
            self.results_layout.removeWidget(button)
            self.results_layout.addWidget(button, i//columns, i % columns)
        self.schedule_preview()
