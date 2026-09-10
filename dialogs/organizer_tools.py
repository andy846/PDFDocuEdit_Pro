"""Organizer option dialogs and cooperative jobs on private PDF snapshots."""

from __future__ import annotations

import threading

from PyQt6.QtCore import QAbstractTableModel, QRectF, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from core.page_plan import POINTS_PER_MM, crop_entries, interleave_entries, parse_page_selection

from .base import ToolDialog


class PlanTableModel(QAbstractTableModel):
    def __init__(self, rows, headers, parent=None):
        super().__init__(parent)
        self.rows, self.headers = rows, headers

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def columnCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and 0 <= index.row() < len(self.rows) and 0 <= index.column() < len(self.headers) and role == Qt.ItemDataRole.DisplayRole:
            return str(self.rows[index.row()][index.column()])
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.headers):
            return self.headers[section]
        return None

    def reset_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()


def plan_rows(entries):
    return [(i + 1, entry.source_label or ("Blank" if entry.source_kind == "blank" else "Current PDF"),
             "—" if entry.source_kind == "blank" else entry.source_page + 1) for i, entry in enumerate(entries)]


class OrganizerWorker(QThread):
    result = pyqtSignal(object)
    failed = pyqtSignal(object)
    progress = pyqtSignal(object, object)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function
        self.cancelled = threading.Event()

    def run(self):
        try:
            from core.pdf_engine import DOCUMENT_LOCK

            with DOCUMENT_LOCK:
                value = self.function(cancelled=self.cancelled.is_set, progress=self.progress.emit)
            self.result.emit(value)
        except Exception as exc:
            self.failed.emit(exc)


class JobDialog(QDialog):
    def __init__(self, title, function, parent):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        self.label = QLabel(title)
        layout.addWidget(self.label)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        layout.addWidget(self.bar)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.cancel_button)
        self.value = None
        self.error = None
        self.worker = OrganizerWorker(function, self)
        self.worker.result.connect(self._result)
        self.worker.failed.connect(self._error)
        self.worker.progress.connect(self._progress)
        self.worker.finished.connect(self.accept)

    def _result(self, value):
        self.value = value

    def _error(self, error):
        self.error = error

    def _progress(self, current, total):
        self.bar.setRange(0, 1000)
        self.bar.setValue(round(current * 1000 / max(1, total)))

    def reject(self):
        if self.worker.isRunning():
            self.worker.cancelled.set()
            self.label.setText("Cancelling at the next safe checkpoint…")
            self.cancel_button.setEnabled(False)
        else:
            super().reject()

    def closeEvent(self, event):
        if self.worker.isRunning():
            self.reject()
            event.ignore()
        else:
            event.accept()


def run_job(parent, title, function):
    dialog = JobDialog(title, function, parent)
    parent._busy = True
    parent.pages._thumb_timer.stop()
    try:
        dialog.worker.start()
        dialog.exec()
        dialog.worker.wait()
        if dialog.error is not None:
            raise dialog.error
        return dialog.value
    finally:
        parent._busy = False
        parent.pages._queue_visible()
        dialog.deleteLater()


class InterleaveDialog(ToolDialog):
    def __init__(self, a, b, reader, parent=None):
        super().__init__("Interleave Pages", "interleave-pages", parent)
        self.a, self.b, self.reader = a, b, reader
        self.plan = []
        options = QHBoxLayout()
        self.first = QComboBox()
        self.first.addItems(["A first", "B first"])
        self.reverse_b = QCheckBox("Reverse B (back-side scan)")
        self.remainder = QComboBox()
        self.remainder.addItems(["Append remaining pages", "Pad missing sides with blank pages"])
        for widget in (self.first, self.reverse_b, self.remainder):
            options.addWidget(widget)
        self._root.addLayout(options)
        self.summary = QLabel()
        self._root.addWidget(self.summary)
        self.model = PlanTableModel([], ["Final page", "Source", "Original page"], self)
        table = QTableView()
        table.setModel(self.model)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(1, 300)
        self._root.addWidget(table, 1)
        self.add_validation()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText("Use This Page Plan")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)
        self.first.currentIndexChanged.connect(self.refresh)
        self.reverse_b.toggled.connect(self.refresh)
        self.remainder.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        try:
            self.plan = interleave_entries(self.a, self.b, b_first=self.first.currentIndex() == 1,
                                           reverse_b=self.reverse_b.isChecked(), pad=self.remainder.currentIndex() == 1,
                                           size_of=self.reader.size)
            self.summary.setText(f"A: {len(self.a)} pages · B: {len(self.b)} pages · Result: {len(self.plan)} pages")
            self.model.reset_rows(plan_rows(self.plan))
            self.ok.setEnabled(True)
            self._validation.hide()
        except Exception as exc:
            self.plan = []
            self.model.reset_rows([])
            self.ok.setEnabled(False)
            self.show_error(f"Cannot build interleave preview: {exc}")


class BlankPagesDialog(ToolDialog):
    def __init__(self, reference_size, parent=None):
        super().__init__("Insert Blank Pages", "organizer-blank-pages", parent)
        self.reference_size = reference_size
        form = QFormLayout()
        self.count = QSpinBox()
        self.count.setRange(1, 10000)
        self.paper = QComboBox()
        self.paper.addItems(["Match reference page", "A4", "Letter", "Custom"])
        self.orientation = QComboBox()
        self.orientation.addItems(["Portrait", "Landscape"])
        self.width_mm, self.height_mm = QDoubleSpinBox(), QDoubleSpinBox()
        for widget in (self.width_mm, self.height_mm):
            widget.setRange(0.1, 5000)
            widget.setDecimals(2)
            widget.setSuffix(" mm")
        self.position = QComboBox()
        for label, value in (("After selection", "after"), ("Before selection", "before"), ("Beginning", "beginning"), ("End", "end")):
            self.position.addItem(label, value)
        for label, widget in (("Count", self.count), ("Position", self.position), ("Paper", self.paper),
                              ("Orientation", self.orientation), ("Width", self.width_mm), ("Height", self.height_mm)):
            form.addRow(label, widget)
        self._root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)
        self.paper.currentIndexChanged.connect(self.refresh)
        self.orientation.currentIndexChanged.connect(self._orientation_changed)
        self.width_mm.valueChanged.connect(self._custom_orientation)
        self.height_mm.valueChanged.connect(self._custom_orientation)
        self.refresh()

    def refresh(self):
        index = self.paper.currentIndex()
        self.orientation.setEnabled(index != 0)
        self.width_mm.setEnabled(index == 3)
        self.height_mm.setEnabled(index == 3)
        if index == 3:
            self._custom_orientation()
            return
        size = [(v / POINTS_PER_MM for v in self.reference_size), (210, 297), (215.9, 279.4)][index]
        width, height = size
        if index != 0 and self.orientation.currentIndex() == 1:
            width, height = height, width
        self.width_mm.setValue(width)
        self.height_mm.setValue(height)

    def _custom_orientation(self):
        if self.paper.currentIndex() != 3 or self.width_mm.value() == self.height_mm.value():
            return
        self.orientation.blockSignals(True)
        self.orientation.setCurrentIndex(int(self.width_mm.value() > self.height_mm.value()))
        self.orientation.blockSignals(False)

    def _orientation_changed(self):
        if self.paper.currentIndex() != 3:
            self.refresh()
            return
        width, height = self.width_mm.value(), self.height_mm.value()
        landscape = self.orientation.currentIndex() == 1
        if (landscape and width < height) or (not landscape and width > height):
            self.width_mm.blockSignals(True)
            self.height_mm.blockSignals(True)
            self.width_mm.setValue(height)
            self.height_mm.setValue(width)
            self.width_mm.blockSignals(False)
            self.height_mm.blockSignals(False)

    def page_size(self):
        if self.paper.currentIndex() == 0:
            return self.reference_size
        return self.width_mm.value() * POINTS_PER_MM, self.height_mm.value() * POINTS_PER_MM


class CropCanvas(QWidget):
    marginsChanged = pyqtSignal(object)

    def __init__(self, pixmap: QPixmap, page_size, parent=None):
        super().__init__(parent)
        self.pixmap, self.page_size = pixmap, page_size
        self.margins = (0., 0., 0., 0.)
        self.anchor = None
        self.setMinimumSize(260, 260)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def image_rect(self):
        area = QRectF(self.rect()).adjusted(10, 10, -10, -10)
        scale = min(area.width() / self.pixmap.width(), area.height() / self.pixmap.height())
        width, height = self.pixmap.width() * scale, self.pixmap.height() * scale
        return QRectF(area.center().x() - width / 2, area.center().y() - height / 2, width, height)

    def paintEvent(self, _event):
        painter = QPainter(self)
        image = self.image_rect()
        painter.drawPixmap(image, self.pixmap, QRectF(self.pixmap.rect()))
        left, top, right, bottom = self.margins
        width, height = (v / POINTS_PER_MM for v in self.page_size)
        crop = image.adjusted(left / width * image.width(), top / height * image.height(),
                              -right / width * image.width(), -bottom / height * image.height())
        painter.setPen(QPen(QColor("#1374e8"), 2))
        painter.setBrush(QColor(20, 110, 230, 25))
        painter.drawRect(crop)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.image_rect().contains(event.position()):
            self.anchor = event.position()

    def mouseMoveEvent(self, event):
        if self.anchor is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._drag(event.position())

    def mouseReleaseEvent(self, event):
        if self.anchor is not None:
            self._drag(event.position())
            self.anchor = None

    def _drag(self, position):
        image = self.image_rect()
        rect = QRectF(self.anchor, position).normalized().intersected(image)
        if rect.width() < 2 or rect.height() < 2:
            return
        width, height = (v / POINTS_PER_MM for v in self.page_size)
        self.margins = ((rect.left() - image.left()) / image.width() * width,
                        (rect.top() - image.top()) / image.height() * height,
                        (image.right() - rect.right()) / image.width() * width,
                        (image.bottom() - rect.bottom()) / image.height() * height)
        self.marginsChanged.emit(self.margins)
        self.update()


class CropDialog(ToolDialog):
    def __init__(self, entries, positions, reader, parent=None):
        super().__init__("Crop Selected Pages", "organizer-crop", parent)
        self.entries, self.positions, self.reader = entries, positions, reader
        self.plan = None
        note = QLabel("Crop changes the visible area; hidden content remains in the PDF. Use Redact to remove sensitive content.")
        note.setWordWrap(True)
        self._root.addWidget(note)
        from .document_dialogs import _fitz_pixmap_image

        reference = entries[positions[0]]
        self.canvas = CropCanvas(QPixmap.fromImage(_fitz_pixmap_image(reader.render(reference, 900))), reader.size(reference))
        self._root.addWidget(self.canvas, 1)
        form = QHBoxLayout()
        self.inputs = []
        for label in ("Left", "Top", "Right", "Bottom"):
            field = QDoubleSpinBox()
            field.setRange(0, 5000)
            field.setDecimals(3)
            field.setSuffix(" mm")
            field.valueChanged.connect(self._numbers)
            self.inputs.append(field)
            form.addWidget(QLabel(label))
            form.addWidget(field)
        self._root.addLayout(form)
        self.canvas.marginsChanged.connect(self._dragged)
        self.add_validation()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(f"Crop {len(positions)} Selected Pages")
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)

    def _numbers(self):
        self.canvas.margins = tuple(field.value() for field in self.inputs)
        self.canvas.update()

    def _dragged(self, margins):
        for field, value in zip(self.inputs, margins, strict=True):
            field.blockSignals(True)
            field.setValue(value)
            field.blockSignals(False)
        self._numbers()

    def _apply(self):
        try:
            self.plan = crop_entries(self.entries, self.positions, tuple(field.value() for field in self.inputs), self.reader)
            self.accept()
        except Exception as exc:
            self.show_error(str(exc))


class SplitPlanDialog(ToolDialog):
    def __init__(self, entries, parent=None):
        super().__init__("Split Page Plan", "organizer-split", parent)
        self.entries, self.groups = entries, []
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItems(["Every page", "Every N pages", "After specified pages"])
        self.interval = QSpinBox()
        self.interval.setRange(1, len(entries))
        self.points = QLineEdit()
        self.points.setPlaceholderText("3, 8, 12")
        self.prefix = QLineEdit("document")
        for label, widget in (("Mode", self.mode), ("N", self.interval), ("Split after", self.points), ("Filename prefix", self.prefix)):
            form.addRow(label, widget)
        self._root.addLayout(form)
        self.model = PlanTableModel([], ["Filename", "Preview pages", "Count"], self)
        table = QTableView()
        table.setModel(self.model)
        table.setColumnWidth(0, 300)
        self._root.addWidget(table, 1)
        self.add_validation()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText("Choose Folder and Export")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)
        for signal in (self.mode.currentIndexChanged, self.interval.valueChanged, self.points.textChanged, self.prefix.textChanged):
            signal.connect(self.refresh)
        self.refresh()

    def refresh(self):
        from .base import windows_safe_filename_component

        self.interval.setEnabled(self.mode.currentIndex() == 1)
        self.points.setEnabled(self.mode.currentIndex() == 2)
        try:
            prefix = self.prefix.text().strip()
            if not prefix or not windows_safe_filename_component(prefix) or any(ord(c) < 32 for c in prefix) or prefix.endswith((".", " ")):
                raise ValueError("Enter a valid filename prefix.")
            count = len(self.entries)
            if self.mode.currentIndex() == 2:
                ends = [p + 1 for p in parse_page_selection(self.points.text(), count)]
                if not ends:
                    raise ValueError("Enter split points, e.g. 3,8.")
            else:
                step = self.interval.value() if self.mode.currentIndex() == 1 else 1
                ends = list(range(step, count + 1, step))
            if not ends or ends[-1] != count:
                ends.append(count)
            start = 0
            self.groups, rows = [], []
            for number, end in enumerate(ends, 1):
                name = f"{prefix}_{number:03d}.pdf"
                self.groups.append((name, self.entries[start:end]))
                rows.append((name, f"{start + 1}–{end}", end - start))
                start = end
            self.model.reset_rows(rows)
            self.ok.setEnabled(True)
            self._validation.hide()
        except ValueError as exc:
            self.groups = []
            self.model.reset_rows([])
            self.ok.setEnabled(False)
            self.show_error(str(exc))
