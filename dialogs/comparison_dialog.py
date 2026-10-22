"""Independent read-only comparison workspace with cooperative background jobs."""
from pathlib import Path

import fitz
from PyQt6.QtCore import Qt, QThreadPool, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.comparison import compare_snapshots, manual_pair, snapshot_file, unpair
from core.diagnostics import log_failure
from core.tasks import FunctionTask
from ui.pdf_canvas import PdfCanvas
from ui.responsive import ResponsiveDialog


class ComparisonDialog(ResponsiveDialog):
    def __init__(self, source_a, sources_b, parent=None):
        """Sources are (label, snapshot callable, revision callable) tuples."""
        super().__init__(parent)
        self.setWindowTitle("Compare PDFs")
        self.setModal(False)
        self.resize(1250, 820)
        self.source_a, self.sources_b = source_a, sources_b
        self._source_b = None
        self._bytes = None
        self._revisions = None
        self._docs = []
        self._task = None
        self._close_pending = False
        self.results = []
        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"A: {source_a[0]} • Read-only snapshots, including unsaved edits"))
        row = QHBoxLayout()
        self.source_combo = QComboBox()
        for label, _, _ in sources_b:
            self.source_combo.addItem(label)
        row.addWidget(QLabel("B:"))
        row.addWidget(self.source_combo, 1)
        self.browse = QPushButton("Choose external PDF…")
        self.browse.clicked.connect(self.choose_external)
        row.addWidget(self.browse)
        self.compare = QPushButton("Compare / Refresh")
        self.compare.clicked.connect(self.start_comparison)
        row.addWidget(self.compare)
        root.addLayout(row)
        command_buttons = {}
        toolbar = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["Visual differences", "Text differences"])
        self.mode.currentIndexChanged.connect(self.show_pair)
        toolbar.addWidget(self.mode)
        for title, step in (("Previous difference", -1), ("Next difference", 1)):
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, delta=step: self.next_difference(delta))
            toolbar.addWidget(button)
            command_buttons["compare.previous" if step < 0 else "compare.next"] = button
        toolbar.addStretch(1)
        root.addLayout(toolbar)
        toolbar = QHBoxLayout()
        self.a_page, self.b_page = QSpinBox(), QSpinBox()
        for label, spin in (("Pair A", self.a_page), ("with B", self.b_page)):
            toolbar.addWidget(QLabel(label))
            spin.setMinimum(1)
            spin.setFixedWidth(125)
            toolbar.addWidget(spin)
        self.pair_button = QPushButton("Pair")
        self.pair_button.clicked.connect(self.pair_pages)
        self.unpair_button = QPushButton("Unpair selected")
        self.unpair_button.clicked.connect(self.unpair_selected)
        toolbar.addWidget(self.pair_button)
        toolbar.addWidget(self.unpair_button)
        toolbar.addStretch(1)
        root.addLayout(toolbar)
        split = QSplitter()
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["A page", "B page", "Difference"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.currentCellChanged.connect(self.show_pair)
        self.table.setColumnWidth(0, 65)
        self.table.setColumnWidth(1, 65)
        self.table.setColumnWidth(2, 100)
        self.table.setMinimumWidth(250)
        split.addWidget(self.table)
        self.canvases, self.empty_labels = [], []
        self._showing_pair = False
        for side, label in enumerate(("A", "B")):
            panel = QWidget()
            layout = QVBoxLayout(panel)
            layout.addWidget(QLabel(label))
            empty = QLabel("Choose a document and compare")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            canvas = PdfCanvas()
            canvas.set_annotations_editable(False)
            canvas.pageChanged.connect(lambda page, side=side: self.navigate_canvas(side, page))
            layout.addWidget(empty)
            layout.addWidget(canvas, 1)
            split.addWidget(panel)
            self.canvases.append(canvas)
            self.empty_labels.append(empty)
        split.setSizes([240, 500, 500])
        root.addWidget(split, 1)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(100)
        root.addWidget(self.details)
        self.status = QLabel("Compare two PDFs without changing either source.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        progress = QHBoxLayout()
        self.bar = QProgressBar()
        self.cancel = QPushButton("Cancel comparison")
        self.cancel.clicked.connect(self.cancel_job)
        progress.addWidget(self.bar, 1)
        progress.addWidget(self.cancel)
        root.addLayout(progress)
        from ui.shortcut_bindings import bind_dialog_commands
        command_buttons.update({"compare.refresh": self.compare, "compare.pair": self.pair_button,
                                "compare.unpair": self.unpair_button})
        self._command_buttons = command_buttons
        bind_dialog_commands(self, command_buttons)
        self._busy(False)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.check_stale)
        self.timer.start()

    def refresh_shortcuts(self):
        from ui.shortcut_bindings import bind_dialog_commands
        bind_dialog_commands(self, self._command_buttons)

    def _busy(self, busy):
        for widget in (self.compare, self.browse, self.source_combo, self.pair_button, self.unpair_button):
            widget.setEnabled(not busy)
        self.cancel.setEnabled(busy)
        self.bar.setVisible(busy)

    def choose_external(self):
        path, _ = QFileDialog.getOpenFileName(self, "Compare with PDF", "", "PDF (*.pdf)")
        if not path:
            return
        try:
            with fitz.open(path) as doc:
                password = ""
                if doc.needs_pass:
                    password, ok = QInputDialog.getText(self, "PDF password", "Password:", QLineEdit.EchoMode.Password)
                    if not ok:
                        return
                if doc.needs_pass and not doc.authenticate(password):
                    raise ValueError("Incorrect password.")
            data = snapshot_file(path, password)
            # Password and file handles are not retained. Confirmed data is private.
            first_snapshot = [data]
            def reload_source():
                if first_snapshot:
                    return first_snapshot.pop()
                with fitz.open(path) as current:
                    protected = bool(current.needs_pass)
                secret = ""
                if protected:
                    secret, accepted = QInputDialog.getText(self, "PDF password", "Password:", QLineEdit.EchoMode.Password)
                    if not accepted:
                        raise ValueError("Refresh cancelled; previous results retained.")
                return snapshot_file(path, secret)
            def revision():
                try:
                    stat = Path(path).stat()
                    return stat.st_mtime_ns, stat.st_size
                except OSError:
                    return "unavailable"
            self.sources_b.append((path, reload_source, revision))
            self.source_combo.addItem(path)
            self.source_combo.setCurrentIndex(self.source_combo.count() - 1)
        except Exception as exc:
            log_failure("Comparison source could not be opened")
            self.status.setText(str(exc))

    def start_comparison(self):
        if self._task is not None:
            return
        index = self.source_combo.currentIndex()
        if index < 0:
            self.status.setText("Choose document B first.")
            return
        try:
            source_b = self.sources_b[index]
            data = (self.source_a[1](), source_b[1]())
            revisions = (self.source_a[2](), source_b[2]())
            self.run_comparison(data, revisions, source_b=source_b)
        except Exception as exc:
            log_failure("Could not create comparison snapshots")
            self.status.setText(str(exc))

    def run_comparison(self, data, revisions, pairs=None, source_b=None):
        if self._task is not None:
            return
        self._busy(True)
        self.status.setText("Comparing private snapshots…")
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        def work(progress, cancelled):
            return compare_snapshots(*data, pairs=pairs, cancelled=cancelled,
                                     progress=lambda n, total: progress(n, total, "Comparing"))
        task = FunctionTask(work, progress_argument="progress", cancel_argument="cancelled")
        self._task = task
        task.signals.progress.connect(lambda n, total, message: self.bar.setValue(int(1000*n/max(1, total))))
        result_source = source_b or self._source_b
        task.signals.result.connect(lambda results: self.install_results(results, data, revisions, result_source))
        task.signals.error.connect(lambda message: self.status.setText("Comparison failed: " + message))
        task.signals.cancelled.connect(lambda: self.status.setText("Comparison cancelled. Previous results retained."))
        task.signals.finished.connect(self.finished_job)
        QThreadPool.globalInstance().start(task)

    def install_results(self, results, data, revisions, source_b=None):
        docs = []
        try:
            for value in data:
                docs.append(fitz.open(stream=value, filetype="pdf"))
            for canvas in self.canvases:
                canvas.clear()
            for doc in self._docs:
                doc.close()
            self._docs, docs = docs, []
            self._bytes, self._revisions = data, revisions
            self._source_b = source_b or self._source_b
            self.results = results
            for canvas, doc in zip(self.canvases, self._docs, strict=True):
                canvas.load_doc(doc)
            self.a_page.setMaximum(self._docs[0].page_count)
            self.b_page.setMaximum(self._docs[1].page_count)
            self.table.blockSignals(True)
            self.table.setRowCount(len(results))
            for row, item in enumerate(results):
                for col, value in enumerate((item.a + 1 if item.a is not None else "—",
                                             item.b + 1 if item.b is not None else "—", item.status)):
                    self.table.setItem(row, col, QTableWidgetItem(str(value)))
            self.table.blockSignals(False)
            self.table.selectRow(0)
            self.show_pair()
            changed = sum(r.status != "Same" for r in results)
            self.status.setText(f"{changed} changed page pairs • {len(results)} total pairs • Sources unchanged")
        except Exception:
            log_failure("Could not display comparison results")
            self.status.setText("Could not display the comparison results.")
        finally:
            for doc in docs:
                doc.close()

    def finished_job(self):
        self._task = None
        self._busy(False)
        if self._close_pending:
            self.close()

    def cancel_job(self):
        if self._task is not None:
            self._task.cancel()
            self.status.setText("Cancelling at the next safe checkpoint…")

    def check_stale(self):
        if self._revisions is None or self._task is not None or self._source_b is None:
            return
        try:
            current = (self.source_a[2](), self._source_b[2]())
        except (RuntimeError, AttributeError):
            current = ("closed", "closed")
        if current != self._revisions:
            self.status.setText("Source document changed. These results are out of date; choose Compare / Refresh.")

    def navigate_canvas(self, side, number):
        if self._showing_pair:
            return
        for row, item in enumerate(self.results):
            if (item.a if side == 0 else item.b) == number:
                self.table.selectRow(row)
                return

    def show_pair(self, *_):
        row = self.table.currentRow()
        if not 0 <= row < len(self.results):
            return
        item = self.results[row]
        self._showing_pair = True
        for index, (canvas, empty, number) in enumerate(zip(self.canvases, self.empty_labels, (item.a, item.b), strict=True)):
            canvas.setVisible(number is not None)
            empty.setVisible(number is None)
            empty.setText("No corresponding page")
            if number is not None:
                canvas.set_page(number)
                if self.mode.currentIndex() == 0:
                    regions = item.a_regions if index == 0 else item.b_regions
                else:
                    regions = [r for t in item.text for r in (t.a_rects if index == 0 else t.b_rects)]
                canvas.show_search_hits(number, [fitz.Rect(r) for r in regions])
        self._showing_pair = False
        self.details.setPlainText("\n".join(f"{t.kind}: {t.before} → {t.after}" for t in item.text)
                                  if item.has_text else "No text layer. Visual comparison only; OCR can be run separately.")

    def next_difference(self, delta):
        if not self.results:
            return
        start = self.table.currentRow()
        for offset in range(1, len(self.results) + 1):
            row = (start + delta * offset) % len(self.results)
            if self.results[row].status != "Same":
                self.table.selectRow(row)
                return

    def pair_pages(self):
        if not self.results:
            return
        try:
            pairs = manual_pair([(r.a, r.b) for r in self.results], self.a_page.value()-1, self.b_page.value()-1)
            self.run_comparison(self._bytes, self._revisions, pairs)
        except ValueError as exc:
            self.status.setText(str(exc))

    def unpair_selected(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.results):
            pairs = unpair([(r.a, r.b) for r in self.results], row)
            self.run_comparison(self._bytes, self._revisions, pairs)

    def reject(self):
        self.close()

    def closeEvent(self, event):
        if self._task is not None:
            self._close_pending = True
            self.cancel_job()
            event.ignore()
            return
        self.timer.stop()
        for canvas in self.canvases:
            canvas.clear()
        for doc in self._docs:
            doc.close()
        self._docs = []
        self._bytes = None
        self.results = []
        event.accept()
        self.done(QDialog.DialogCode.Rejected)
