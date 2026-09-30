"""PDF overlay setup with background preflight and true PDF-rendered preview."""

from __future__ import annotations

import csv
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import QAbstractTableModel, Qt, QThreadPool, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from core.overlay import (
    OverlayFileResult,
    OverlayJob,
    OverlayOptions,
    OverlayPreflight,
    render_overlay_preview,
    scan_overlay_inputs,
)
from core.pdf_engine import DOCUMENT_LOCK
from core.tasks import FunctionTask

from .base import ToolDialog, windows_safe_filename_component

_pool: QThreadPool | None = None


def overlay_pool() -> QThreadPool:
    global _pool
    if _pool is None or sip.isdeleted(_pool):
        _pool = QThreadPool()
        _pool.setMaxThreadCount(1)
    return _pool


class OverlayJobsModel(QAbstractTableModel):
    HEADERS = ("Target PDF", "Pages", "Output", "Status")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.jobs: tuple[OverlayJob, ...] = ()

    def set_jobs(self, jobs: tuple[OverlayJob, ...]) -> None:
        self.beginResetModel()
        self.jobs = jobs
        self.endResetModel()

    def rowCount(self, parent=None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.jobs)

    def columnCount(self, parent=None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.jobs):
            return None
        job = self.jobs[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return (job.source.name, job.pages or "—", job.output.name,
                    job.problem or "Ready")[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{job.source}\n→ {job.output}" + (f"\n{job.problem}" if job.problem else "")
        return None


def _discover_targets(mode: int, current: Path | None, selected: str, recursive: bool,
                      template: Path, output_folder: Path, is_cancelled) -> list[Path]:
    if mode == 0:
        return [current] if current else []
    if mode == 1:
        return [Path(selected)] if selected else []
    folder = Path(selected)
    if not folder.is_dir():
        raise ValueError("Choose a target folder")
    iterator = folder.rglob("*") if recursive else folder.iterdir()
    targets = []
    for path in iterator:
        if is_cancelled():
            raise InterruptedError("Overlay scan cancelled")
        if not path.is_file() or path.suffix.casefold() != ".pdf":
            continue
        resolved = path.resolve()
        if resolved == template:
            continue
        if recursive and output_folder != folder.resolve() and output_folder in resolved.parents:
            continue
        targets.append(resolved)
    return sorted(targets)


def _preflight_worker(template: Path, mode: int, current: Path | None, selected: str,
                      recursive: bool, output_folder: Path, suffix: str, overwrite: bool,
                      preview_override: Path | None, is_cancelled=None) -> OverlayPreflight:
    cancelled = is_cancelled or (lambda: False)
    sources = _discover_targets(mode, current, selected, recursive, template,
                                output_folder, cancelled)
    overrides = {current: preview_override} if current and preview_override else None
    with DOCUMENT_LOCK:
        return scan_overlay_inputs(template, sources, output_folder, suffix, overwrite,
                                   overrides, cancelled)


def _preview_worker(template: Path, target: Path, page: int, options: OverlayOptions):
    with DOCUMENT_LOCK:
        return render_overlay_preview(template, target, page, options)


class OverlayDialog(ToolDialog):
    def __init__(self, current_path: Path | None, parent=None, *,
                 current_preview_path: Path | None = None, current_modified: bool = False):
        super().__init__("PDF Overlay", "overlay-pdf", parent)
        self.current_path = Path(current_path).resolve() if current_path else None
        self.current_preview_path = current_preview_path
        self.current_modified = current_modified
        self.details: dict[str, object] | None = None
        self._preflight: OverlayPreflight | None = None
        self._scan_task: FunctionTask | None = None
        self._preview_task: FunctionTask | None = None
        self._scan_generation = 0
        self._preview_generation = 0
        self._closed = False
        self._images: tuple[QPixmap, QPixmap] | None = None

        inputs = QGroupBox("1 · PDFs and output")
        form = QFormLayout(inputs)
        self.template = QLineEdit()
        self.template.setReadOnly(True)
        form.addRow("Template PDF", self._picker(self.template, "Choose template PDF"))
        self.target_mode = QComboBox()
        self.target_mode.addItems(["Current PDF", "One PDF", "Folder (batch)"])
        if not self.current_path:
            self.target_mode.setCurrentIndex(1)
            self.target_mode.model().item(0).setEnabled(False)
        self.target_mode.currentIndexChanged.connect(self._mode_changed)
        form.addRow("Targets", self.target_mode)
        self.target = QLineEdit(str(self.current_path or ""))
        self.target.setReadOnly(True)
        form.addRow("Target path", self._picker(self.target, "Choose target PDF or folder", target=True))
        self.output = QLineEdit(str(self.current_path.parent) if self.current_path else "")
        self.output.setReadOnly(True)
        form.addRow("Output folder", self._picker(self.output, "Choose output folder", folder=True))
        self.suffix = QLineEdit("_overlay")
        form.addRow("Filename suffix", self.suffix)
        self.recursive = QCheckBox("Include subfolders")
        form.addRow("", self.recursive)
        self.overwrite = QCheckBox("Allow overwriting existing outputs")
        form.addRow("", self.overwrite)
        self._root.addWidget(inputs)

        placement = QGroupBox("2 · Placement")
        options_form = QFormLayout(placement)
        self.layer = self._combo(("Over target content", "foreground"),
                                 ("Under target content", "background"))
        options_form.addRow("Layer", self.layer)
        self.mapping = self._combo(("Repeat last template page", "repeat_last"),
                                   ("Cycle template pages", "cycle"),
                                   ("Matching pages only", "matching_only"))
        options_form.addRow("Page pairing", self.mapping)
        self.scale_mode = self._combo(("Fit within target page", "fit"),
                                      ("Original template size", "actual"))
        options_form.addRow("Size", self.scale_mode)
        self.alignment = self._combo(*((label, value) for label, value in (
            ("Top left", "top-left"), ("Top", "top"), ("Top right", "top-right"),
            ("Left", "left"), ("Centre", "center"), ("Right", "right"),
            ("Bottom left", "bottom-left"), ("Bottom", "bottom"),
            ("Bottom right", "bottom-right"))))
        self.alignment.setCurrentIndex(4)
        options_form.addRow("Align", self.alignment)
        self.rotation = self._combo(*((f"{degree}°", degree) for degree in (0, 90, 180, 270)))
        options_form.addRow("Rotate template", self.rotation)
        offsets = QWidget()
        offsets_row = QHBoxLayout(offsets)
        offsets_row.setContentsMargins(0, 0, 0, 0)
        self.offset_x = self._offset_spin()
        self.offset_y = self._offset_spin()
        offsets_row.addWidget(QLabel("X"))
        offsets_row.addWidget(self.offset_x)
        offsets_row.addWidget(QLabel("Y"))
        offsets_row.addWidget(self.offset_y)
        options_form.addRow("Offset", offsets)
        self._root.addWidget(placement)

        list_group = QGroupBox("3 · Batch preflight")
        list_layout = QVBoxLayout(list_group)
        self.summary = QLabel("Choose a template and output folder to inspect targets.")
        self.summary.setWordWrap(True)
        list_layout.addWidget(self.summary)
        self.model = OverlayJobsModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setMinimumHeight(125)
        self.table.setMaximumHeight(180)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.clicked.connect(lambda _: self._schedule_preview())
        list_layout.addWidget(self.table)
        self._root.addWidget(list_group)

        preview_group = QGroupBox("4 · Before / after preview")
        preview_layout = QVBoxLayout(preview_group)
        page_row = QHBoxLayout()
        page_row.addWidget(QLabel("Target page"))
        self.preview_page = QSpinBox()
        self.preview_page.setRange(1, 1)
        self.preview_page.valueChanged.connect(self._schedule_preview)
        page_row.addWidget(self.preview_page)
        page_row.addWidget(QLabel("Zoom"))
        self.preview_zoom = self._combo(("Fit", 0), ("100%", 1), ("150%", 1.5),
                                        ("200%", 2))
        self.preview_zoom.currentIndexChanged.connect(self._display_images)
        page_row.addWidget(self.preview_zoom)
        page_row.addStretch(1)
        self.preview_status = QLabel("Select a ready target to preview.")
        page_row.addWidget(self.preview_status)
        preview_layout.addLayout(page_row)
        images = QHBoxLayout()
        self.before_label = self._image_label("Before")
        self.after_label = self._image_label("After")
        self.before_scroll = self._image_scroll(self.before_label)
        self.after_scroll = self._image_scroll(self.after_label)
        images.addWidget(self.before_scroll, 1)
        images.addWidget(self.after_scroll, 1)
        preview_layout.addLayout(images)
        self._root.addWidget(preview_group)

        self.add_validation()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.apply_button.setText("Apply Overlay")
        self.apply_button.setEnabled(False)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)

        self._scan_timer = QTimer(self)
        self._scan_timer.setSingleShot(True)
        self._scan_timer.setInterval(220)
        self._scan_timer.timeout.connect(self._start_scan)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(220)
        self._preview_timer.timeout.connect(self._start_preview)
        for edit in (self.template, self.target, self.output, self.suffix):
            edit.textChanged.connect(self._schedule_scan)
        for control in (self.recursive, self.overwrite):
            control.toggled.connect(self._schedule_scan)
        for control in (self.layer, self.mapping, self.scale_mode, self.alignment, self.rotation):
            control.currentIndexChanged.connect(self._schedule_preview)
        for control in (self.offset_x, self.offset_y):
            control.valueChanged.connect(self._schedule_preview)
        self._mode_changed()

    @staticmethod
    def _combo(*values):
        combo = QComboBox()
        for label, value in values:
            combo.addItem(label, value)
        return combo

    @staticmethod
    def _offset_spin() -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(-10000.0, 10000.0)
        spin.setDecimals(2)
        spin.setSuffix(" mm")
        return spin

    @staticmethod
    def _image_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setMinimumSize(190, 215)
        label.setObjectName("overlayPreviewImage")
        return label

    @staticmethod
    def _image_scroll(label: QLabel) -> QScrollArea:
        area = QScrollArea()
        area.setWidget(label)
        area.setWidgetResizable(True)
        area.setMinimumSize(190, 215)
        area.setMaximumHeight(270)
        return area

    def _picker(self, edit: QLineEdit, title: str, *, target: bool = False,
                folder: bool = False) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        button = QPushButton("Browse…")

        def browse() -> None:
            choose_folder = folder or (target and self.target_mode.currentIndex() == 2)
            if choose_folder:
                value = QFileDialog.getExistingDirectory(self, title, edit.text())
            else:
                value, _ = QFileDialog.getOpenFileName(self, title, edit.text(), "PDF (*.pdf)")
            if value:
                edit.setText(value)

        button.clicked.connect(browse)
        row.addWidget(edit, 1)
        row.addWidget(button)
        return widget

    def drop_extensions(self) -> set[str] | None:
        return {".pdf"}

    def add_dropped_paths(self, paths: list[str]) -> None:
        if not self.template.text():
            self.template.setText(paths[0])
            paths = paths[1:]
        if paths:
            self.target_mode.setCurrentIndex(1)
            self.target.setText(paths[0])

    def _mode_changed(self) -> None:
        current = self.target_mode.currentIndex() == 0
        self.target.setEnabled(not current)
        self.recursive.setEnabled(self.target_mode.currentIndex() == 2)
        if current and self.current_path:
            self.target.setText(str(self.current_path))
        self._schedule_scan()

    def options(self) -> OverlayOptions:
        return OverlayOptions(
            mapping=self.mapping.currentData(), layer=self.layer.currentData(),
            scale_mode=self.scale_mode.currentData(), alignment=self.alignment.currentData(),
            rotation=self.rotation.currentData(), offset_x_mm=self.offset_x.value(),
            offset_y_mm=self.offset_y.value(),
        )

    def _schedule_scan(self, *_args) -> None:
        if self._closed:
            return
        self._scan_generation += 1
        if self._scan_task:
            self._scan_task.cancel()
        self._preflight = None
        self._clear_preview()
        self.apply_button.setEnabled(False)
        self.summary.setText("Inspecting targets…")
        self._scan_timer.start()

    def _start_scan(self) -> None:
        template = Path(self.template.text())
        output = Path(self.output.text())
        if not template.is_file() or not output.is_dir():
            self.model.set_jobs(())
            self.summary.setText("Choose a valid template PDF and output folder.")
            return
        generation = self._scan_generation
        task = FunctionTask(
            _preflight_worker, template.resolve(), self.target_mode.currentIndex(),
            self.current_path, self.target.text(), self.recursive.isChecked(),
            output.resolve(), self.suffix.text(), self.overwrite.isChecked(),
            self.current_preview_path, cancel_argument="is_cancelled",
        )
        self._scan_task = task
        task.signals.result.connect(lambda result, g=generation: self._scan_ready(g, result))
        task.signals.error.connect(lambda error, g=generation: self._scan_failed(g, error))
        overlay_pool().start(task)

    def _scan_ready(self, generation: int, result: OverlayPreflight) -> None:
        if self._closed or generation != self._scan_generation:
            return
        self._scan_task = None
        self._preflight = result
        self.model.set_jobs(result.jobs)
        errors = sum(bool(job.problem) for job in result.jobs)
        total_pages = sum(job.pages for job in result.jobs)
        self.summary.setText(
            f"Template: {result.template_pages} page(s) · Targets: {len(result.jobs)} · "
            f"Target pages: {total_pages} · Issues: {errors}"
        )
        suffix_valid = windows_safe_filename_component(self.suffix.text())
        if not suffix_valid:
            self.summary.setText(self.summary.text() + " · Invalid filename suffix")
        self.apply_button.setEnabled(
            result.valid and suffix_valid and bool(self.suffix.text() or self.overwrite.isChecked())
        )
        ready_row = next((i for i, job in enumerate(result.jobs) if not job.problem), None)
        if ready_row is not None:
            self.table.selectRow(ready_row)
        self._schedule_preview()

    def _scan_failed(self, generation: int, error: str) -> None:
        if self._closed or generation != self._scan_generation:
            return
        self._scan_task = None
        self._preflight = None
        self._clear_preview()
        self.model.set_jobs(())
        self.summary.setText(error)
        self.apply_button.setEnabled(False)

    def _schedule_preview(self, *_args) -> None:
        if self._closed:
            return
        self._preview_generation += 1
        if self._preview_task:
            self._preview_task.cancel()
        self._preview_timer.start()

    def _start_preview(self) -> None:
        if not self._preflight or not self._preflight.jobs:
            return
        row = max(0, self.table.currentIndex().row())
        job = self._preflight.jobs[min(row, len(self._preflight.jobs) - 1)]
        if job.problem or not job.pages:
            self.preview_status.setText("Select a ready target.")
            return
        self.preview_page.blockSignals(True)
        self.preview_page.setMaximum(job.pages)
        self.preview_page.blockSignals(False)
        source = (self.current_preview_path if job.source == self.current_path
                  and self.current_preview_path else job.source)
        generation = self._preview_generation
        self.preview_status.setText("Rendering…")
        task = FunctionTask(
            _preview_worker, Path(self.template.text()), source,
            self.preview_page.value() - 1, self.options(),
        )
        self._preview_task = task
        task.signals.result.connect(lambda value, g=generation: self._preview_ready(g, value))
        task.signals.error.connect(lambda error, g=generation: self._preview_failed(g, error))
        overlay_pool().start(task)

    def _preview_ready(self, generation: int, value) -> None:
        if self._closed or generation != self._preview_generation:
            return
        self._preview_task = None
        before, after, count = value
        left, right = QPixmap(), QPixmap()
        left.loadFromData(before)
        right.loadFromData(after)
        self._images = left, right
        self._display_images()
        self.preview_status.setText(f"Page {self.preview_page.value()} of {count}")

    def _preview_failed(self, generation: int, error: str) -> None:
        if self._closed or generation != self._preview_generation:
            return
        self._preview_task = None
        self._clear_preview()
        self.preview_status.setText(f"Preview unavailable: {error}")

    def _clear_preview(self) -> None:
        self._images = None
        self.before_label.setPixmap(QPixmap())
        self.after_label.setPixmap(QPixmap())
        self.before_label.setText("Before")
        self.after_label.setText("After")

    def _display_images(self) -> None:
        if not self._images:
            return
        zoom = self.preview_zoom.currentData()
        for label, area, pixmap in zip(
            (self.before_label, self.after_label),
            (self.before_scroll, self.after_scroll), self._images, strict=True,
        ):
            if zoom:
                area.setWidgetResizable(False)
                label.setMinimumSize(0, 0)
                image = pixmap.scaled(
                    pixmap.size() * zoom,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                label.setPixmap(image)
                label.resize(image.size())
            else:
                area.setWidgetResizable(True)
                label.setMinimumSize(190, 215)
                label.setPixmap(pixmap.scaled(
                    max(190, area.viewport().width() - 8),
                    max(200, area.viewport().height() - 8),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._display_images()

    def _validate(self) -> None:
        if self._preflight is None or not self._preflight.valid:
            self.show_error("Resolve the batch preflight issues before applying the overlay.")
            return
        if not self.suffix.text() and not self.overwrite.isChecked():
            self.show_error("Enter a suffix or allow overwriting existing outputs.")
            return
        if self.suffix.text() and not windows_safe_filename_component(self.suffix.text()):
            self.show_error("Filename suffix contains invalid Windows characters.")
            return
        targets = [job.source for job in self._preflight.jobs]
        if (self.current_modified and self.current_path in targets and
                not self.suffix.text() and self.overwrite.isChecked()):
            self.show_error("Save the current PDF before an in-place overlay.")
            return
        if not self.suffix.text() and self.overwrite.isChecked():
            answer = QMessageBox.question(
                self, "Replace source PDFs?",
                f"This will replace {len(targets)} source PDF file(s) after each output is validated. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.details = {
            "template": str(Path(self.template.text()).resolve()),
            "targets": [str(path) for path in targets],
            "output_folder": str(Path(self.output.text()).resolve()),
            "suffix": self.suffix.text(),
            "overwrite": self.overwrite.isChecked(),
            "options": self.options(),
        }
        self.accept()

    def _stop_background(self) -> None:
        self._closed = True
        self._scan_timer.stop()
        self._preview_timer.stop()
        if self._scan_task:
            self._scan_task.cancel()
        if self._preview_task:
            self._preview_task.cancel()

    def done(self, result: int) -> None:
        self._stop_background()
        super().done(result)

    def closeEvent(self, event) -> None:
        self._stop_background()
        super().closeEvent(event)


class OverlayResultsDialog(QDialog):
    def __init__(self, results: list[OverlayFileResult], output_folder: Path, parent=None):
        super().__init__(parent)
        self.results = results
        self.output_folder = output_folder
        self.setWindowTitle("PDF overlay results")
        self.resize(720, 440)
        layout = QVBoxLayout(self)
        done = sum(item.status == "completed" for item in results)
        failed = sum(item.status == "failed" for item in results)
        skipped = sum(item.status == "skipped" for item in results)
        layout.addWidget(QLabel(f"Completed: {done} · Failed: {failed} · Skipped: {skipped}"))
        self.model = OverlayResultsModel(results, self)
        table = QTableView()
        table.setModel(self.model)
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        row = QHBoxLayout()
        export = QPushButton("Export CSV…")
        export.clicked.connect(self._export_csv)
        row.addWidget(export)
        open_folder = QPushButton("Open output folder")
        open_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_folder))))
        row.addWidget(open_folder)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)

    def _export_csv(self) -> None:
        output, _ = QFileDialog.getSaveFileName(
            self, "Export overlay results", str(self.output_folder / "overlay-results.csv"), "CSV (*.csv)"
        )
        if not output:
            return
        try:
            with Path(output).open("w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.writer(stream)
                writer.writerow(("Target", "Output", "Status", "Detail"))
                writer.writerows((str(item.source), str(item.output), item.status, item.detail)
                                for item in self.results)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))


class OverlayResultsModel(QAbstractTableModel):
    HEADERS = ("Target", "Output", "Status", "Detail")

    def __init__(self, results: list[OverlayFileResult], parent=None):
        super().__init__(parent)
        self.results = results

    def rowCount(self, parent=None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.results)

    def columnCount(self, parent=None) -> int:
        return 0 if parent is not None and parent.isValid() else 4

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.results):
            return None
        item = self.results[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return (item.source.name, item.output.name, item.status, item.detail)[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{item.source}\n→ {item.output}\n{item.detail}"
        return None
