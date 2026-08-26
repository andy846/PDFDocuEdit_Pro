"""Non-modal document inspector, preflight and smart-detection panel."""

from __future__ import annotations

import csv
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.analysis import (
    AnalysisRequest,
    Finding,
    FindingGroup,
    FindingSet,
    FindingStatus,
    InspectionReport,
    Severity,
    TextRule,
)


class AnalysisPanel(QFrame):
    """Per-session analysis UI. Engine page numbers remain zero based."""

    runRequested = pyqtSignal(object)
    jumpRequested = pyqtSignal(int)
    organizeRequested = pyqtSignal(object)
    extractRequested = pyqtSignal(object)
    closed = pyqtSignal()

    DETECTORS = (
        ("exact_blank", "Exact Blank"),
        ("near_blank", "Near Blank"),
        ("text", "Text Exists"),
        ("specific_text", "Specific Text"),
        ("image", "Raster Image"),
        ("vector", "Vector Graphics"),
        ("annotation", "Annotation"),
        ("form", "Form Field"),
        ("barcode", "Barcode"),
        ("qr", "QR Code"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("analysisPanel")
        self.setMinimumWidth(390)
        self._report: InspectionReport | None = None
        self._result_rows: list[Finding | FindingGroup] = []
        self._stale = False
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        header = QHBoxLayout()
        title = QLabel("Document Analysis")
        title.setObjectName("panelTitle")
        header.addWidget(title)
        header.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.closed.emit)
        header.addWidget(close)
        root.addLayout(header)

        self.status = QLabel("Choose an analysis and select Run.")
        self.status.setObjectName("secondary")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._inspector_tab(), "Inspector")
        self.tabs.addTab(self._preflight_tab(), "Preflight")
        self.tabs.addTab(self._detection_tab(), "Smart Detection")
        self.tabs.addTab(self._results_tab(), "Results")
        root.addWidget(self.tabs, 1)

    @staticmethod
    def _wrap(widget: QWidget) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(widget)
        return tab

    def _inspector_tab(self) -> QWidget:
        tabs = QTabWidget()
        self.overview_table = self._table(["Property", "Value"])
        self.page_table = self._table(
            [
                "Page",
                "Size",
                "mm",
                "Orientation",
                "Rotation",
                "MediaBox",
                "CropBox",
                "BleedBox",
                "TrimBox",
                "ArtBox",
            ]
        )
        self.font_table = self._table(
            ["Font", "Type", "Encoding", "Embedded", "Subset", "Pages", "XRef"]
        )
        self.image_table = self._table(
            [
                "Page",
                "Pixels",
                "Compression",
                "Color",
                "BPC",
                "Alpha",
                "Effective DPI",
                "Placement",
                "XRef",
            ]
        )
        self.color_table = self._table(["Color space", "Occurrences", "Parsing"])
        tabs.addTab(self._wrap(self.overview_table), "Overview")
        tabs.addTab(self._wrap(self.page_table), "Pages")
        tabs.addTab(self._wrap(self.font_table), "Fonts")
        tabs.addTab(self._wrap(self.image_table), "Images")
        tabs.addTab(self._wrap(self.color_table), "Color")
        return tabs

    @staticmethod
    def _table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _preflight_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()
        self.profile = QComboBox()
        self.profile.addItem("General Office", "general")
        self.profile.addItem("Digital Print", "digital")
        self.profile.addItem("Production Print", "production")
        form.addRow("Profile", self.profile)
        self.standard = QComboBox()
        self.standard.addItem("Not run", None)
        for profile in (
            "1b",
            "1a",
            "2b",
            "2u",
            "2a",
            "3b",
            "3u",
            "3a",
            "4",
            "4e",
            "4f",
            "ua1",
            "ua2",
        ):
            self.standard.addItem(
                f"PDF/{'UA-' + profile[-1] if profile.startswith('ua') else 'A-' + profile}",
                profile,
            )
        form.addRow("Formal validation", self.standard)
        layout.addLayout(form)
        note = QLabel(
            "PDF/UA results cover machine-verifiable checks. PDF/X is reported only as readiness checks."
        )
        note.setWordWrap(True)
        note.setObjectName("secondary")
        layout.addWidget(note)
        self.validation_summary_label = QLabel("Formal validation has not been run.")
        self.validation_summary_label.setWordWrap(True)
        self.validation_summary_label.setObjectName("secondary")
        layout.addWidget(self.validation_summary_label)
        button = QPushButton("Run Inspector + Preflight")
        button.clicked.connect(
            lambda: self.runRequested.emit(self.build_request(preflight=True))
        )
        layout.addWidget(button)
        layout.addStretch(1)
        return tab

    def _detection_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.detector_checks: dict[str, QCheckBox] = {}
        for key, label in self.DETECTORS:
            box = QCheckBox(label)
            self.detector_checks[key] = box
            layout.addWidget(box)
        form = QFormLayout()
        self.text_query = QLineEdit()
        self.text_query.setPlaceholderText("Text or regular expression")
        form.addRow("Specific text", self.text_query)
        self.case_sensitive = QCheckBox("Case sensitive")
        self.whole_word = QCheckBox("Whole word")
        self.regex = QCheckBox("Regular expression")
        options = QWidget()
        options_layout = QHBoxLayout(options)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.addWidget(self.case_sensitive)
        options_layout.addWidget(self.whole_word)
        options_layout.addWidget(self.regex)
        form.addRow("Match", options)
        self.dpi = QSpinBox()
        self.dpi.setRange(72, 600)
        self.dpi.setValue(200)
        form.addRow("Render DPI", self.dpi)
        self.near_blank = QDoubleSpinBox()
        self.near_blank.setRange(0.001, 20.0)
        self.near_blank.setDecimals(3)
        self.near_blank.setSuffix(" %")
        self.near_blank.setValue(0.1)
        form.addRow("Near-blank threshold", self.near_blank)
        self.ocr = QCheckBox("Use OCR fallback when available")
        form.addRow("OCR", self.ocr)
        self.barcode_value = QLineEdit()
        form.addRow("Barcode value filter", self.barcode_value)
        self.barcode_match = QComboBox()
        self.barcode_match.addItem("Contains", "contains")
        self.barcode_match.addItem("Exact", "exact")
        form.addRow("Barcode match", self.barcode_match)
        layout.addLayout(form)
        button = QPushButton("Run Smart Detection")
        button.clicked.connect(lambda: self.runRequested.emit(self.build_request()))
        layout.addWidget(button)
        layout.addStretch(1)
        return tab

    def _results_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        controls = QHBoxLayout()
        self.group_results = QCheckBox("Group repetitive page findings")
        self.group_results.setChecked(True)
        self.group_results.toggled.connect(self._refresh_results)
        controls.addWidget(self.group_results)
        controls.addStretch(1)
        controls.addWidget(QLabel("Rows"))
        self.export_mode = QComboBox()
        self.export_mode.addItem("Grouped findings", "grouped")
        self.export_mode.addItem("Detailed findings", "detailed")
        controls.addWidget(self.export_mode)
        layout.addLayout(controls)

        self.results = self._table(
            [
                "Severity",
                "Category",
                "Source",
                "Rule",
                "Summary",
                "Page(s)",
                "Count",
                "Status",
                "Details",
                "Object Ref",
                "BBox",
                "Value",
            ]
        )
        self.results.cellClicked.connect(self._jump_result)
        layout.addWidget(self.results, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.result_action_buttons: dict[str, QWidget] = {}

        select_all = QPushButton("Select all")
        select_all.clicked.connect(self.results.selectAll)
        buttons.addWidget(select_all)
        self.result_action_buttons["Select all"] = select_all

        copy_pages = QPushButton("Copy pages")
        copy_pages.clicked.connect(self._copy_pages)
        buttons.addWidget(copy_pages)
        self.result_action_buttons["Copy pages"] = copy_pages

        export_button = QToolButton()
        export_button.setText("Export")
        export_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        export_menu = QMenu(export_button)
        export_menu.addAction("Page list (CSV)...").triggered.connect(
            self._export_page_list
        )
        export_menu.addSeparator()
        export_menu.addAction("Findings (CSV)...").triggered.connect(self._export_csv)
        export_menu.addAction("Findings (Excel)...").triggered.connect(
            self._export_xlsx
        )
        export_button.setMenu(export_menu)
        buttons.addWidget(export_button)
        self.result_action_buttons["Export"] = export_button
        self.export_actions_menu = export_menu

        extract = QPushButton("Extract")
        extract.clicked.connect(self._extract)
        buttons.addWidget(extract)
        self.result_action_buttons["Extract"] = extract

        remove = QPushButton("Remove pages")
        remove.clicked.connect(self._organize)
        buttons.addWidget(remove)
        self.result_action_buttons["Remove pages"] = remove

        buttons.addStretch(1)
        layout.addLayout(buttons)
        return tab

    def build_request(self, *, preflight: bool = False) -> AnalysisRequest:
        detectors = frozenset(
            key for key, box in self.detector_checks.items() if box.isChecked()
        )
        text_rule = TextRule(
            query=self.text_query.text(),
            case_sensitive=self.case_sensitive.isChecked(),
            whole_word=self.whole_word.isChecked(),
            regex=self.regex.isChecked(),
        )
        return AnalysisRequest(
            detectors=detectors,
            preflight_profile=str(self.profile.currentData()) if preflight else None,
            text_rule=text_rule,
            barcode_value=self.barcode_value.text(),
            barcode_match=str(self.barcode_match.currentData()),
            scan_dpi=self.dpi.value(),
            near_blank_threshold=self.near_blank.value() / 100.0,
            ocr_fallback=self.ocr.isChecked(),
            standard_profile=self.standard.currentData() if preflight else None,
        )

    def set_running(self, running: bool) -> None:
        self.status.setText(
            "Analysis is running page by page…" if running else "Analysis complete."
        )

    def set_report(self, report: InspectionReport) -> None:
        self._report = report
        self._stale = False
        self.overview_table.setRowCount(0)
        overview = dict(report.overview)
        overview.update(
            {
                "page_size_groups": self._page_groups(report),
                "font_resources": len(report.fonts),
                "image_occurrences": len(report.images),
                "color_resources (best-effort)": ", ".join(
                    f"{key}: {value}" for key, value in report.colors.items()
                )
                or "None",
                "standard_validation": report.standard_status,
            }
        )
        for key, value in overview.items():
            row = self.overview_table.rowCount()
            self.overview_table.insertRow(row)
            self.overview_table.setItem(
                row, 0, QTableWidgetItem(str(key).replace("_", " ").title())
            )
            self.overview_table.setItem(row, 1, QTableWidgetItem(str(value)))
        self._populate_records(
            self.page_table,
            report.pages,
            (
                "page",
                "size_name",
                "dimensions",
                "orientation",
                "rotation",
                "media_box",
                "crop_box",
                "bleed_box",
                "trim_box",
                "art_box",
            ),
        )
        self._populate_records(
            self.font_table,
            report.fonts,
            ("name", "type", "encoding", "embedded", "subset", "pages", "xref"),
        )
        self._populate_records(
            self.image_table,
            report.images,
            (
                "page",
                "pixels",
                "compression",
                "colorspace",
                "bpc",
                "has_mask",
                "dpi",
                "bbox",
                "xref",
            ),
        )
        color_rows = [
            {"space": space, "count": count, "parsing": "best-effort"}
            for space, count in report.colors.items()
        ]
        self._populate_records(
            self.color_table,
            color_rows,
            ("space", "count", "parsing"),
        )

        summary = report.validation_summary
        if summary is None:
            self.validation_summary_label.setText(report.standard_status)
        elif summary.compliant is True:
            self.validation_summary_label.setText(
                f"{summary.standard}: PASSED ({summary.passed_rule_count} rules checked)"
            )
        elif summary.compliant is False:
            self.validation_summary_label.setText(
                f"{summary.standard}: FAILED - {summary.failed_rule_count} unique rule "
                f"failure(s), {summary.failed_check_count} affected object check(s)"
            )
        else:
            self.validation_summary_label.setText(
                f"{summary.standard}: validation unavailable - {summary.message}"
            )
        report.finding_set.normalize()
        self._refresh_results()
        self.tabs.setCurrentIndex(3 if report.finding_set.findings else 0)

    @staticmethod
    def _page_groups(report: InspectionReport) -> str:
        groups: dict[str, int] = {}
        for page in report.pages:
            label = f"{page['size_name']} {page['width_mm']}×{page['height_mm']} mm"
            groups[label] = groups.get(label, 0) + 1
        return "; ".join(f"{key} × {value}" for key, value in groups.items()) or "None"

    @staticmethod
    def _populate_records(
        table: QTableWidget,
        rows: list[dict[str, object]],
        fields: tuple[str, ...],
    ) -> None:
        table.setRowCount(0)
        for record in rows:
            row = table.rowCount()
            table.insertRow(row)
            for column, field in enumerate(fields):
                value = record.get(field, "")
                if field == "page" and isinstance(value, int):
                    value = value + 1
                elif field == "pages" and isinstance(value, (tuple, list)):
                    value = ", ".join(str(page + 1) for page in value)
                elif isinstance(value, bool):
                    value = "Yes" if value else "No"
                table.setItem(row, column, QTableWidgetItem(str(value)))

    def _display_rows(
        self, grouped: bool | None = None
    ) -> list[Finding | FindingGroup]:
        if not self._report:
            return []
        use_groups = self.group_results.isChecked() if grouped is None else grouped
        if use_groups:
            return list(self._report.finding_set.groups())
        self._report.finding_set.normalize()
        return list(self._report.finding_set.findings)

    @staticmethod
    def _row_data(item: Finding | FindingGroup) -> tuple[object, ...]:
        if isinstance(item, FindingGroup):
            pages = item.pages
            count = len(pages) if item.group_id == "blank-pages" else item.count
            bboxes = {str(value.bbox) for value in item.findings if value.bbox}
            values = {value.value for value in item.findings if value.value}
            return (
                str(item.severity),
                item.category,
                str(item.source),
                item.rule_id,
                item.summary,
                pages,
                count,
                str(item.status),
                item.details,
                item.object_ref,
                "; ".join(sorted(bboxes)),
                "; ".join(sorted(values)),
            )
        return (
            str(item.severity),
            item.category or "Document",
            str(item.source),
            item.rule_id,
            item.summary,
            item.all_pages(),
            1,
            str(item.status),
            item.details,
            item.object_ref,
            str(item.bbox or ""),
            item.value,
        )

    def _refresh_results(self) -> None:
        if not hasattr(self, "results"):
            return
        self._result_rows = self._display_rows()
        self.results.setRowCount(0)
        for item in self._result_rows:
            values = self._row_data(item)
            row = self.results.rowCount()
            self.results.insertRow(row)
            for column, value in enumerate(values):
                if column == 5:
                    pages = tuple(value)
                    display = (
                        "Document"
                        if not pages
                        else ", ".join(str(page + 1) for page in pages)
                    )
                    cell = QTableWidgetItem(display)
                    cell.setData(Qt.ItemDataRole.UserRole, pages)
                else:
                    cell = QTableWidgetItem(str(value))
                if column == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, item)
                self.results.setItem(row, column, cell)

        groups = self._report.finding_set.groups() if self._report else ()
        active = [group for group in groups if group.status == FindingStatus.ACTIVE]
        counts = {
            severity: sum(group.severity == severity for group in active)
            for severity in Severity
        }
        affected_pages = {page for group in active for page in group.pages}
        expected = sum(group.status == FindingStatus.EXPECTED for group in groups)
        ignored = sum(group.status == FindingStatus.IGNORED for group in groups)
        self.status.setText(
            f"Issues: {len(active)} - Errors: {counts[Severity.ERROR]} - "
            f"Warnings: {counts[Severity.WARNING]} - Info: {counts[Severity.INFO]} - "
            f"Affected pages: {len(affected_pages)} - Expected: {expected} - "
            f"Ignored: {ignored}"
        )

    def mark_stale(self) -> None:
        if self._report is not None:
            self._stale = True
            self.status.setText(
                "Results are stale because the document changed. Run analysis again before page operations."
            )

    def finding_set(self) -> FindingSet | None:
        return self._report.finding_set if self._report else None

    def _selected_result_rows(self) -> list[Finding | FindingGroup]:
        if not self._report:
            return []
        indexes = sorted(
            {index.row() for index in self.results.selectionModel().selectedRows()}
        )
        return [
            self._result_rows[index]
            for index in indexes
            if 0 <= index < len(self._result_rows)
        ]

    def _selected_findings(self) -> tuple[Finding, ...]:
        selected = self._selected_result_rows()
        findings: list[Finding] = []
        seen: set[int] = set()
        for item in selected:
            for finding in item.findings if isinstance(item, FindingGroup) else (item,):
                if id(finding) not in seen:
                    seen.add(id(finding))
                    findings.append(finding)
        return tuple(findings)

    def _selected_pages(self) -> tuple[int, ...]:
        if not self._report:
            return ()
        selected = self._selected_result_rows()
        pages = {
            page
            for item in selected
            for page in (
                item.pages if isinstance(item, FindingGroup) else item.all_pages()
            )
        }
        return tuple(sorted(pages)) or self._report.finding_set.pages()

    def _jump_result(self, row: int, _column: int = 0) -> None:
        if 0 <= row < len(self._result_rows):
            item = self._result_rows[row]
            pages = item.pages if isinstance(item, FindingGroup) else item.all_pages()
            if pages:
                self.jumpRequested.emit(pages[0])

    def _go_selected(self) -> None:
        rows = self.results.selectionModel().selectedRows()
        if rows:
            self._jump_result(rows[0].row())

    def _select_detected_rows(self) -> None:
        self.results.clearSelection()
        selected = 0
        for row, item in enumerate(self._result_rows):
            pages = item.pages if isinstance(item, FindingGroup) else item.all_pages()
            if not pages:
                continue
            selected += 1
            for column in range(self.results.columnCount()):
                cell = self.results.item(row, column)
                if cell is not None:
                    cell.setSelected(True)
        self.status.setText(
            f"Selected {selected} result row(s) containing detected pages."
        )

    def _copy_pages(self) -> None:
        pages = self._selected_pages()
        QGuiApplication.clipboard().setText(", ".join(str(page + 1) for page in pages))
        self.status.setText(f"Copied {len(pages)} page number(s).")

    def _export_page_list(self) -> None:
        pages = self._selected_pages()
        if not pages:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export page list", "detected-pages.csv", "CSV (*.csv)"
        )
        if not path:
            return
        with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Page"])
            writer.writerows((page + 1,) for page in pages)
        self.status.setText(f"Exported {len(pages)} page number(s).")

    @staticmethod
    def _export_headers() -> list[str]:
        return [
            "Severity",
            "Category",
            "Source",
            "Rule",
            "Summary",
            "Page",
            "Pages",
            "Count",
            "Status",
            "Details",
            "ObjectRef",
            "BBox",
            "Value",
        ]

    def _export_rows(self) -> list[list[object]]:
        grouped = self.export_mode.currentData() == "grouped"
        records: list[list[object]] = []
        for item in self._display_rows(grouped):
            row = self._row_data(item)
            pages = tuple(row[5])
            records.append(
                [
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    pages[0] + 1 if len(pages) == 1 else "",
                    ", ".join(str(page + 1) for page in pages),
                    row[6],
                    row[7],
                    row[8],
                    row[9],
                    row[10],
                    row[11],
                ]
            )
        return records

    def _export_csv(self) -> None:
        if not self._report:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export findings", "findings.csv", "CSV (*.csv)"
        )
        if not path:
            return
        with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(self._export_headers())
            writer.writerows(self._export_rows())
        self.status.setText(f"Exported {Path(path).name}.")

    def _export_xlsx(self) -> None:
        if not self._report:
            return
        try:
            from openpyxl import Workbook
        except ImportError:
            self.status.setText(
                "XLSX export requires openpyxl; CSV export is available."
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export findings", "findings.xlsx", "Excel workbook (*.xlsx)"
        )
        if not path:
            return
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Findings"
        sheet.append(self._export_headers())
        for row in self._export_rows():
            sheet.append(
                [
                    str(value) if isinstance(value, (tuple, list)) else value
                    for value in row
                ]
            )
        sheet.freeze_panes = "A2"
        workbook.save(path)
        self.status.setText(f"Exported {Path(path).name}.")

    def _set_selected_status(self, status: FindingStatus) -> None:
        if not self._report:
            return
        findings = self._selected_findings()
        if not findings:
            self.status.setText("Select one or more findings first.")
            return
        self._report.finding_set.set_status(findings, status)
        self._refresh_results()

    def _extract(self) -> None:
        pages = self._selected_pages()
        if pages:
            self.extractRequested.emit(pages)

    def _organize(self) -> None:
        if self._stale:
            self.status.setText(
                "Stale results cannot be sent to Organizer. Run analysis again."
            )
            return
        if not self._report:
            return
        selected = self._selected_findings()
        if not selected:
            self.status.setText(
                "Select detected findings first; Organizer will require confirmation."
            )
            return
        source = self._report.finding_set
        scoped = FindingSet(
            source.document_id,
            source.revision,
            source.request,
            list(selected),
            source.started_at,
            source.finished_at,
        )
        self.organizeRequested.emit(scoped)


__all__ = ["AnalysisPanel"]
