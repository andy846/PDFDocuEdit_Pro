"""Animated, searchable and capability-aware feature navigation."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QSettings,
    QSize,
    Qt,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.capabilities import CapabilityId, detect_capabilities
from styles.tokens import D, S

from .icons import app_icon, app_pixmap, icon
from .motion import MotionNavButton


@dataclass(frozen=True)
class ToolItem:
    key: str
    label: str
    icon_name: str
    asset_name: str | None = None
    capability: CapabilityId | None = None


# Keyboard shortcut hints shown in tool tooltips (matches menu bar shortcuts).
SHORTCUT_HINTS: dict[str, str] = {
    "rotate": "F6",
    "insert": "F7",
    "delete": "F8",
    "extract": "F9",
    "split": "F10",
}


class CollapsibleSection(QWidget):
    """One animated tool group that turns into an icon-only run when collapsed."""

    def __init__(self, key: str, title: str, animations_enabled: bool, parent=None):
        super().__init__(parent)
        self.key = key
        self._animations_enabled = animations_enabled
        self._sidebar_collapsed = False
        self._filtering = False
        self._logical_expanded = bool(QSettings().value(f"sidebar/section/{key}", True, bool))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(S.XXS)

        self.header = QToolButton()
        self.header.setObjectName("sidebarSectionButton")
        self.header.setText(title)
        self.header.setAccessibleName(f"{title} section")
        self.header.setAccessibleDescription(
            "Expanded" if self._logical_expanded else "Collapsed"
        )
        self.header.setCheckable(True)
        self.header.setChecked(self._logical_expanded)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setIconSize(QSize(14, 14))
        self.header.clicked.connect(self._header_clicked)
        layout.addWidget(self.header)

        self.body = QWidget()
        self.body.setObjectName("sidebarSectionBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, S.SM)
        self.body_layout.setSpacing(S.XXS)
        layout.addWidget(self.body)
        self._animation = QPropertyAnimation(self.body, b"maximumHeight", self)
        self._animation.setDuration(160)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.finished.connect(self._animation_finished)
        self._update_header_icon()
        QTimer.singleShot(0, lambda: self._apply_expanded(False))

    def add_button(self, button: QPushButton) -> None:
        self.body_layout.addWidget(button)

    def _header_clicked(self, checked: bool) -> None:
        self._logical_expanded = checked
        QSettings().setValue(f"sidebar/section/{self.key}", checked)
        self._update_header_icon()
        self._apply_expanded(True)

    def _update_header_icon(self) -> None:
        self.header.setIcon(
            icon("chevron-down" if self._logical_expanded else "chevron-right", 14)
        )

    def _natural_height(self) -> int:
        self.body.adjustSize()
        return max(0, self.body.sizeHint().height())

    def _should_expand(self) -> bool:
        return self._sidebar_collapsed or self._filtering or self._logical_expanded

    def _apply_expanded(self, animate: bool) -> None:
        expanded = self._should_expand()
        target = self._natural_height() if expanded else 0
        self._animation.stop()
        self.body.setVisible(True)
        if animate and self._animations_enabled and not self._sidebar_collapsed:
            self._animation.setStartValue(self.body.height())
            self._animation.setEndValue(target)
            self._animation.start()
        else:
            self.body.setMaximumHeight(target)
            if not expanded:
                self.body.hide()

    def _animation_finished(self) -> None:
        if not self._should_expand():
            self.body.hide()
        else:
            self.body.setMaximumHeight(self._natural_height())

    def set_sidebar_collapsed(self, collapsed: bool) -> None:
        self._sidebar_collapsed = collapsed
        self.header.setVisible(not collapsed)
        self._apply_expanded(False)

    def set_filtering(self, filtering: bool, has_matches: bool) -> None:
        self._filtering = filtering
        self.setVisible(has_matches or not filtering)
        if self.isVisible():
            QTimer.singleShot(0, lambda: self._apply_expanded(False))

    def set_animations_enabled(self, enabled: bool) -> None:
        self._animations_enabled = enabled

    def refresh_icon(self) -> None:
        self._update_header_icon()


class SidePanel(QFrame):
    toolRequested = pyqtSignal(str)
    collapsedChanged = pyqtSignal(bool)

    DOCUMENT_TOOLS = {
        "search",
        "rotate",
        "insert",
        "delete",
        "extract",
        "order",
        "sort",
        "split",
        "info",
        "pdf_to_word",
        "extract_text",
        "encrypt",
        "decrypt",
        "highlight",
        "underline",
        "strikeout",
        "note",
        "ink",
        "rect",
        "redact",
        "stamp",
        "signature",
        "image",
        "watermark",
    }

    SECTIONS = (
        (
            "pages",
            "Page Operations",
            (
                ToolItem("search", "Search document", "search", "Search.png"),
                ToolItem("insert", "Insert pages", "files", "insert.png"),
                ToolItem("delete", "Delete pages", "trash", "delete.png"),
                ToolItem("extract", "Extract pages", "scissors", "Extract-page.png"),
                ToolItem("order", "Order pages", "list-tree", "sorting.png"),
                ToolItem("sort", "Organize pages", "layers", "visual_organize.png"),
                ToolItem("split", "Split PDF", "scissors", "Split.png"),
                ToolItem("rotate", "Rotate pages", "rotate-cw"),
                ToolItem("info", "Document information", "info", "info.png"),
            ),
        ),
        (
            "annotate",
            "Annotate",
            (
                ToolItem("highlight", "Highlight text", "highlighter"),
                ToolItem("underline", "Underline text", "underline"),
                ToolItem("strikeout", "Strikethrough text", "strikethrough"),
                ToolItem("note", "Sticky note", "message-square"),
                ToolItem("ink", "Freehand drawing", "pen-line"),
                ToolItem("rect", "Rectangle", "square"),
                ToolItem("redact", "Redact content", "eraser"),
                ToolItem("stamp", "Rubber stamp", "stamp"),
                ToolItem("signature", "Signature image", "signature"),
                ToolItem("image", "Insert image", "image"),
                ToolItem("watermark", "Add watermark", "layers"),
            ),
        ),
        (
            "convert",
            "Conversion",
            (
                ToolItem(
                    "pdf_to_word",
                    "PDF to Word",
                    "file-text",
                    "PDF-to-Word.png",
                    CapabilityId.PDF_TO_WORD,
                ),
                ToolItem(
                    "office_to_pdf",
                    "Office to PDF",
                    "files",
                    "doc_to_PDF.png",
                    CapabilityId.OFFICE_TO_PDF,
                ),
                ToolItem("txt_to_pdf", "Text to PDF", "file-text", "txt_to_PDF.png"),
                ToolItem(
                    "postscript",
                    "PostScript to PDF",
                    "file-text",
                    "postscript.png",
                    CapabilityId.POSTSCRIPT,
                ),
            ),
        ),
        (
            "tools",
            "Utilities",
            (
                ToolItem("find_file", "Find and open PDF", "search", "search_pdf.png"),
                ToolItem(
                    "page_report",
                    "Page count report",
                    "table",
                    "PDF-report.png",
                    CapabilityId.SPREADSHEET,
                ),
                ToolItem("extract_text", "Extract text region", "file-text", "Extract-text.png"),
                ToolItem("merge", "Merge PDFs", "files", "Merge-PDF.png"),
                ToolItem("overlay", "PDF overlay", "layers", "overlay.png"),
                ToolItem("batch_print", "Batch print", "printer", "Batch_print.png"),
                ToolItem("compress", "Compress PDFs", "files", "compress.png"),
                ToolItem("deep_search", "Deep search", "search", "deep_search.png"),
                ToolItem(
                    "merge_sheet",
                    "Merge CSV / Excel",
                    "table",
                    "merge_csv_excel.png",
                    CapabilityId.SPREADSHEET,
                ),
                ToolItem("barcode", "Barcode / QR code", "scan", "qrcode.png", CapabilityId.BARCODE),
                ToolItem("barcode_batch", "Batch Read Barcode/QR Code", "scan", "batch_qrcode.png", CapabilityId.BARCODE),
            ),
        ),
        (
            "security",
            "Security",
            (
                ToolItem("encrypt", "Encrypt PDF", "lock", "encrypt.png"),
                ToolItem("decrypt", "Remove security", "unlock", "decrypt.png"),
            ),
        ),
    )

    def __init__(self, collapsed: bool = False, animations_enabled: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("leftPanel")
        self._collapsed = collapsed
        self._animations_enabled = animations_enabled
        self._panel_width = D.SIDEBAR_W
        self._active_key: str | None = None
        self._document_available = False
        self._document_encrypted = False
        self._buttons: dict[str, MotionNavButton] = {}
        self._items: dict[str, ToolItem] = {}
        self._sections: list[CollapsibleSection] = []
        self._width_animation = QPropertyAnimation(self, b"panelWidth", self)
        self._width_animation.setDuration(180)
        self._width_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._width_animation.finished.connect(self._finish_width_animation)
        self._build()
        self.set_collapsed(collapsed, animate=False)

    @pyqtProperty(int)
    def panelWidth(self) -> int:  # noqa: N802 - Qt property naming
        return self._panel_width

    @panelWidth.setter
    def panelWidth(self, value: int) -> None:  # noqa: N802 - Qt property naming
        self._panel_width = value
        self.setMinimumWidth(value)
        self.setMaximumWidth(value)
        splitter = self.parentWidget()
        if isinstance(splitter, QSplitter):
            sizes = splitter.sizes()
            if len(sizes) >= 2:
                total = sum(sizes)
                context = sizes[2] if len(sizes) > 2 else 0
                sizes[0] = value
                sizes[1] = max(0, total - value - context)
                splitter.setSizes(sizes)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(S.SM, S.SM, S.SM, S.SM)
        layout.setSpacing(S.SM)

        self._header = QWidget()
        self._header.setObjectName("sidebarHeader")
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(S.XS, S.XS, 0, S.XS)
        header_layout.setSpacing(S.SM)
        self._brand_mark = QLabel()
        self._brand_mark.setObjectName("sidebarBrandMark")
        self._brand_mark.setPixmap(app_pixmap("Main_menu.png", 30))
        self._brand_mark.setFixedSize(34, 34)
        self._brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self._brand_mark)
        self._brand_copy = QWidget()
        brand_layout = QVBoxLayout(self._brand_copy)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(0)
        title = QLabel("PDF Workspace")
        title.setObjectName("sidebarTitle")
        subtitle = QLabel("Tools & automation")
        subtitle.setObjectName("sidebarSubtitle")
        brand_layout.addWidget(title)
        brand_layout.addWidget(subtitle)
        header_layout.addWidget(self._brand_copy, 1)
        self._toggle = QToolButton()
        self._toggle.setObjectName("sidebarCollapseButton")
        self._toggle.setIconSize(QSize(18, 18))
        self._toggle.setAccessibleName("Collapse tool navigation")
        self._toggle.clicked.connect(lambda: self.set_collapsed(not self._collapsed))
        header_layout.addWidget(self._toggle)
        layout.addWidget(self._header)

        self._search = QLineEdit()
        self._search.setObjectName("sidebarSearch")
        self._search.setPlaceholderText("Filter tools")
        self._search.setClearButtonEnabled(True)
        self._search_action = self._search.addAction(
            icon("search", 16), QLineEdit.ActionPosition.LeadingPosition
        )
        self._search.textChanged.connect(self._filter_tools)
        layout.addWidget(self._search)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("sidebarScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("sidebarContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, S.MD)
        content_layout.setSpacing(S.XS)
        capabilities = detect_capabilities()
        for section_key, title, items in self.SECTIONS:
            section = CollapsibleSection(section_key, title, self._animations_enabled)
            for item in items:
                button = MotionNavButton(item.label)
                button.setObjectName("sidebarNavButton")
                button.setCheckable(True)
                button.setAutoExclusive(False)
                button.setProperty("section", section_key)
                button.setIcon(self._item_icon(item))
                hint = SHORTCUT_HINTS.get(item.key, "")
                tooltip = f"{item.label} ({hint})" if hint else item.label
                button.setToolTip(tooltip)
                button.setAccessibleName(item.label)
                button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                button.clicked.connect(
                    lambda _checked=False, key=item.key: self._activate_and_emit(key)
                )
                if item.capability:
                    capability = capabilities[item.capability]
                    button.setEnabled(capability.available)
                    if not capability.available:
                        button.setToolTip(
                            f"{item.label}\nUnavailable: {capability.reason}\n{capability.guidance}"
                        )
                section.add_button(button)
                self._buttons[item.key] = button
                self._items[item.key] = item
            content_layout.addWidget(section)
            self._sections.append(section)
        content_layout.addStretch(1)
        self._scroll.setWidget(content)
        layout.addWidget(self._scroll, 1)

        self._footer = QWidget()
        self._footer.setObjectName("sidebarFooter")
        footer_layout = QHBoxLayout(self._footer)
        footer_layout.setContentsMargins(S.SM, S.XS, S.SM, 0)
        footer_layout.setSpacing(S.SM)
        status_dot = QLabel("●")
        status_dot.setObjectName("sidebarStatusDot")
        status_dot.setAccessibleName("Application ready")
        self._tool_count = QLabel(f"{len(self._buttons)} tools")
        self._tool_count.setObjectName("sidebarFooterText")
        footer_layout.addWidget(status_dot)
        footer_layout.addWidget(self._tool_count)
        footer_layout.addStretch(1)
        layout.addWidget(self._footer)

    def _item_icon(self, item: ToolItem):
        return app_icon(item.asset_name, 24) if item.asset_name else icon(item.icon_name, 22)

    def _activate_and_emit(self, key: str) -> None:
        self.set_active_tool(key)
        self._buttons[key].animate_click()
        self.toolRequested.emit(key)

    def _filter_tools(self, value: str) -> None:
        query = value.strip().casefold()
        visible_count = 0
        for section, (_key, _title, items) in zip(self._sections, self.SECTIONS, strict=True):
            matches = 0
            for item in items:
                visible = not query or query in item.label.casefold()
                self._buttons[item.key].setVisible(visible)
                matches += int(visible)
            visible_count += matches
            section.set_filtering(bool(query), matches > 0)
        self._tool_count.setText(
            f"{visible_count} matching tools" if query else f"{len(self._buttons)} tools"
        )

    def set_collapsed(self, collapsed: bool, animate: bool = True) -> None:
        self._collapsed = collapsed
        target = D.SIDEBAR_COLLAPSED_W if collapsed else D.SIDEBAR_W
        self._brand_mark.setVisible(not collapsed)
        self._brand_copy.setVisible(not collapsed)
        self._search.setVisible(not collapsed)
        self._footer.setVisible(not collapsed)
        self._scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            if collapsed
            else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._toggle.setIcon(icon("chevron-right" if collapsed else "chevron-left", 18))
        self._toggle.setToolTip("Expand tools" if collapsed else "Collapse tools")
        self._toggle.setAccessibleName("Expand tool navigation" if collapsed else "Collapse tool navigation")
        for section in self._sections:
            section.set_sidebar_collapsed(collapsed)
        for key, button in self._buttons.items():
            button.setText("" if collapsed else self._items[key].label)
            button.setProperty("collapsed", collapsed)
            button.style().unpolish(button)
            button.style().polish(button)
        self._width_animation.stop()
        if animate and self._animations_enabled:
            self._width_animation.setStartValue(self.width())
            self._width_animation.setEndValue(target)
            self._width_animation.start()
        else:
            self.panelWidth = target
        self.collapsedChanged.emit(collapsed)

    def _finish_width_animation(self) -> None:
        self.panelWidth = D.SIDEBAR_COLLAPSED_W if self._collapsed else D.SIDEBAR_W

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_animations_enabled(self, enabled: bool) -> None:
        self._animations_enabled = enabled
        for section in self._sections:
            section.set_animations_enabled(enabled)
        for button in self._buttons.values():
            button.set_animations_enabled(enabled)

    def refresh_capabilities(self) -> None:
        self._refresh_availability()

    def set_document_available(self, available: bool, encrypted: bool = False) -> None:
        self._document_available = available
        self._document_encrypted = encrypted
        self._refresh_availability()

    def _refresh_availability(self) -> None:
        capabilities = detect_capabilities()
        for key, item in self._items.items():
            button = self._buttons[key]
            button.setToolTip(item.label)
            if key in self.DOCUMENT_TOOLS and not self._document_available:
                button.setEnabled(False)
                button.setToolTip(f"{item.label}\nOpen a PDF to use this tool.")
                continue
            if key == "decrypt" and not self._document_encrypted:
                button.setEnabled(False)
                button.setToolTip(f"{item.label}\nThe open PDF has no password security.")
                continue
            if item.capability is not None:
                capability = capabilities[item.capability]
                button.setEnabled(capability.available)
                if not capability.available:
                    button.setToolTip(
                        f"{item.label}\nUnavailable: {capability.reason}\n{capability.guidance}"
                    )
                continue
            button.setEnabled(True)

    def set_active_tool(self, key: str | None) -> None:
        self._active_key = key
        for item_key, button in self._buttons.items():
            active = item_key == key
            button.setChecked(active)
            button.setProperty("active", active)
            button.style().unpolish(button)
            button.style().polish(button)

    def refresh_icons(self) -> None:
        self._brand_mark.setPixmap(app_pixmap("Main_menu.png", 30))
        self._toggle.setIcon(icon("chevron-right" if self._collapsed else "chevron-left", 18))
        self._search_action.setIcon(icon("search", 16))
        for section in self._sections:
            section.refresh_icon()
        for key, item in self._items.items():
            self._buttons[key].setIcon(self._item_icon(item))
