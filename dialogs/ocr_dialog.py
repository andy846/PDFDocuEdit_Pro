"""OCR workbench dialogs."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from core.ocr import OCRMode, OCRRequest, OCRResult
from core.ocr_language import OCR_LANGUAGE_OPTIONS, normalize_ocr_language
from core.pdf_engine import parse_page_range


class OCRDialog(QDialog):
    def __init__(
        self,
        source: Path,
        page_count: int,
        current_page: int,
        password: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.source = source
        self.page_count = page_count
        self.current_page = current_page
        self.password = password
        self.request: OCRRequest | None = None
        self.setWindowTitle("OCR")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Extract UTF-8 text or add an invisible searchable text layer. "
            "The original PDF is never replaced."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()

        self.mode = QComboBox()
        self.mode.addItem("Extract text", OCRMode.EXTRACT_TEXT)
        self.mode.addItem("Create searchable PDF", OCRMode.SEARCHABLE_PDF)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        form.addRow("Mode", self.mode)

        self.scope = QComboBox()
        self.scope.addItem("All pages", "all")
        self.scope.addItem(f"Current page ({current_page + 1})", "current")
        self.scope.addItem("Custom pages", "custom")
        self.scope.currentIndexChanged.connect(self._scope_changed)
        form.addRow("Pages", self.scope)

        self.custom_pages = QLineEdit()
        self.custom_pages.setPlaceholderText("e.g. 1-5, 8")
        self.custom_pages.setEnabled(False)
        form.addRow("Custom range", self.custom_pages)

        self.language = QComboBox()
        for label, language in OCR_LANGUAGE_OPTIONS:
            self.language.addItem(label, normalize_ocr_language(language))
        form.addRow("Language", self.language)

        self.dpi = QSpinBox()
        self.dpi.setRange(72, 600)
        self.dpi.setValue(300)
        self.dpi.setSuffix(" DPI")
        form.addRow("Resolution", self.dpi)

        output_row = QHBoxLayout()
        self.output = QLineEdit()
        output_row.addWidget(self.output, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        output_row.addWidget(browse)
        form.addRow("Output", output_row)
        layout.addLayout(form)

        note = QLabel(
            "OCR runs page by page with progress and cancellation. Searchable PDF "
            "keeps original images, page sizes, rotations, and unselected pages."
        )
        note.setWordWrap(True)
        note.setObjectName("secondary")
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._mode_changed()

    def _scope_changed(self) -> None:
        self.custom_pages.setEnabled(self.scope.currentData() == "custom")

    def _mode_changed(self) -> None:
        mode = self.mode.currentData()
        suffix = ".pdf" if mode == OCRMode.SEARCHABLE_PDF else ".txt"
        current = Path(self.output.text()) if self.output.text().strip() else None
        if current is None or current.suffix.casefold() in {".pdf", ".txt"}:
            self.output.setText(str(self.source.with_name(f"{self.source.stem}_OCR{suffix}")))

    def _browse(self) -> None:
        mode = self.mode.currentData()
        filter_ = "PDF (*.pdf)" if mode == OCRMode.SEARCHABLE_PDF else "Text (*.txt)"
        value, _ = QFileDialog.getSaveFileName(
            self, "Save OCR output", self.output.text(), filter_
        )
        if value:
            self.output.setText(value)

    def selected_pages(self) -> tuple[int, ...]:
        scope = self.scope.currentData()
        if scope == "all":
            return tuple(range(self.page_count))
        if scope == "current":
            return (self.current_page,)
        return tuple(parse_page_range(self.custom_pages.text(), self.page_count))

    def accept(self) -> None:
        try:
            pages = self.selected_pages()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid page range", str(exc))
            return
        if not pages:
            QMessageBox.warning(self, "OCR", "Choose at least one page.")
            return
        mode = self.mode.currentData()
        output_text = self.output.text().strip()
        if not output_text:
            QMessageBox.warning(self, "OCR", "Choose an output file.")
            return
        target = Path(output_text)
        suffix = ".pdf" if mode == OCRMode.SEARCHABLE_PDF else ".txt"
        if target.suffix.casefold() != suffix:
            target = target.with_suffix(suffix)
        if target.resolve() == self.source.resolve():
            QMessageBox.warning(self, "OCR", "Choose a new file; the original cannot be replaced.")
            return
        overwrite = False
        if target.exists():
            answer = QMessageBox.question(
                self,
                "Replace OCR output?",
                f"{target.name} already exists. Replace it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            overwrite = True
        self.request = OCRRequest(
            source_path=str(self.source),
            pages=pages,
            mode=mode,
            language=str(self.language.currentData()),
            dpi=self.dpi.value(),
            output_path=str(target),
            password=self.password,
            overwrite=overwrite,
        )
        super().accept()


class OCRTextResultDialog(QDialog):
    def __init__(self, result: OCRResult, parent=None):
        super().__init__(parent)
        self.result = result
        self.setWindowTitle("OCR Text")
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        label = QLabel(
            f"Extracted {len(result.pages)} page(s). Text is UTF-8 and can be copied or saved."
        )
        layout.addWidget(label)
        self.preview = QTextEdit()
        self.preview.setPlainText(result.text)
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview, 1)
        row = QHBoxLayout()
        copy = QPushButton("Copy all")
        copy.clicked.connect(lambda: self.preview.selectAll())
        copy.clicked.connect(self.preview.copy)
        row.addWidget(copy)
        save = QPushButton("Save as…")
        save.clicked.connect(self._save_as)
        row.addWidget(save)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)

    def _save_as(self) -> None:
        initial = self.result.output_path or "OCR.txt"
        value, _ = QFileDialog.getSaveFileName(self, "Save OCR text", initial, "Text (*.txt)")
        if not value:
            return
        target = Path(value)
        if target.suffix.casefold() != ".txt":
            target = target.with_suffix(".txt")
        target.write_text(self.result.text, encoding="utf-8")

