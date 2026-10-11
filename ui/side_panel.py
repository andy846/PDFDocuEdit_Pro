"""Animated, searchable and capability-aware feature navigation."""

from __future__ import annotations

from dataclasses import dataclass, replace

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QPropertyAnimation,
    QSettings,
    QSize,
    Qt,
    QTimer,
    pyqtProperty,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.capabilities import CapabilityId, detect_capabilities
from styles.tokens import D, S

from .icons import app_icon, icon
from .tool_navigation import FavouritesDialog, ToolNavButton, ToolPopup


@dataclass(frozen=True)
class ToolItem:
    key: str
    label: str
    icon_name: str
    asset_name: str | None = None
    capability: CapabilityId | None = None
    description: str = ""
    search_aliases: str = ""


# Keyboard shortcut hints shown in tool tooltips (matches menu bar shortcuts).
SHORTCUT_HINTS: dict[str, str] = {
    "rotate": "F6",
    "insert": "F7",
    "delete": "F8",
    "extract": "F9",
    "split": "F10",
    "highlight": "Ctrl+Alt+H",
    "underline": "Ctrl+Alt+U",
    "strikeout": "Ctrl+Alt+S",
    "squiggly": "Ctrl+Alt+Q",
    "note": "Ctrl+Alt+N",
    "ink": "Ctrl+Alt+K",
    "rect": "Ctrl+Alt+R",
    "line": "Ctrl+Alt+L",
    "arrow": "Ctrl+Alt+A",
    "ellipse": "Ctrl+Alt+E",
    "polygon": "Ctrl+Alt+P",
    "freetext_typewriter": "Ctrl+Alt+T",
    "freetext_box": "Ctrl+Alt+B",
    "freetext_callout": "Ctrl+Alt+C",
    "redact": "Ctrl+Alt+D",
    "stamp": "Ctrl+Alt+M",
    "signature": "Ctrl+Alt+G",
    "image": "Ctrl+Alt+I",
    "watermark": "Ctrl+Alt+W",
    "font_inspect": "Ctrl+Alt+F",
}


CATEGORY_LAYOUT = (
    (
        "search_inspect",
        "Search & Inspect",
        "search",
        ("search", "deep_search", "find_file", "info", "font_inspect", "smart_detection", "compare_pdf"),
    ),
    (
        "documents",
        "Pages & Documents",
        "files",
        ("insert", "delete", "extract", "order", "sort", "split", "rotate", "merge"),
    ),
    (
        "edit",
        "Annotate & Edit",
        "pen-line",
        (
            "highlight",
            "underline",
            "strikeout",
            "squiggly",
            "note",
            "ink",
            "rect",
            "line",
            "arrow",
            "ellipse",
            "polygon",
            "freetext_typewriter",
            "freetext_box",
            "freetext_callout",
            "image",
            "signature",
            "stamp",
            "watermark",
            "fill_form",
            "redact",
        ),
    ),
    (
        "conversion",
        "Convert",
        "file-text",
        ("ocr", "pdf_to_word", "office_to_pdf", "txt_to_pdf", "postscript"),
    ),
    (
        "production",
        "Production & Data",
        "printer",
        (
            "pdf_production",
            "overlay",
            "batch_print",
            "compress",
            "page_report",
            "extract_text",
            "merge_sheet",
            "barcode",
            "barcode_batch",
        ),
    ),
    ("protection", "Security", "lock", ("encrypt", "decrypt")),
)

SEARCH_ALIASES = {
    "search": "find text normal search 搜尋 搜索",
    "deep_search": "folder files cross document search 跨檔 搜尋 搜索",
    "merge": "combine join concatenate 合併 合并",
    "extract": "selected pages export 擷取 提取",
    "sort": "reorder organize page arrangement 排序 整理",
    "pdf_production": "font preflight safe embed flatten repair normalise normalize 字體 字体 平面化 修復 修复",
    "batch_print": "printer print printing 列印 打印",
    "font_inspect": "font typeface 字體 字体",
    "image": "picture png jpg 圖片 图片",
    "signature": "handwritten sign 簽名 签名",
}


TOOL_DESCRIPTIONS = {
    "search": "Find text in the current PDF and work with matching pages.",
    "deep_search": "Search text across a folder or multiple PDFs.",
    "find_file": "Find and open a PDF by file name or location.",
    "info": "View document metadata, page dimensions and security information.",
    "font_inspect": "Click text to inspect its font, size and embedding status.",
    "smart_detection": "Inspect page content and detect reusable document regions.",
    "compare_pdf": "Compare two PDFs and review page differences.",
    "insert": "Insert blank pages or pages from another PDF.",
    "delete": "Delete selected pages from the current PDF.",
    "extract": "Save selected pages as a separate PDF.",
    "order": "Change page order using page numbers.",
    "sort": "Visually organize, move and reorder PDF pages.",
    "split": "Split a PDF into separate documents.",
    "rotate": "Rotate the selected PDF pages.",
    "merge": "Combine PDFs in a chosen order using the Merge workbench.",
    "highlight": "Highlight selected text with a colour annotation.",
    "underline": "Underline selected text.",
    "strikeout": "Strike through selected text.",
    "squiggly": "Mark text with a wavy underline.",
    "note": "Add a sticky note comment.",
    "ink": "Draw freehand ink annotations.",
    "rect": "Draw a rectangle annotation.",
    "line": "Draw a straight line annotation.",
    "arrow": "Draw an arrow annotation.",
    "ellipse": "Draw an ellipse or circle annotation.",
    "polygon": "Draw a polygon annotation.",
    "freetext_typewriter": "Place typewriter text on a PDF page.",
    "freetext_box": "Add an editable text box annotation.",
    "freetext_callout": "Add a text callout with a pointer.",
    "stamp": "Place a rubber stamp annotation.",
    "watermark": "Add a text or image watermark.",
    "fill_form": "Enter values in supported PDF form fields.",
    "redact": "Mark and permanently remove sensitive content.",
    "ocr": "Recognize scanned text to make pages searchable.",
    "pdf_to_word": "Convert a PDF to a Word document.",
    "office_to_pdf": "Convert an Office document to PDF where supported.",
    "txt_to_pdf": "Create a PDF from a text file.",
    "postscript": "Convert a PostScript file to PDF.",
    "overlay": "Overlay PDF page content using the existing PDF overlay tool.",
    "batch_print": "Send multiple PDFs to a printer with batch settings.",
    "compress": "Reduce PDF file sizes and compare the results.",
    "page_report": "Create a page-count report for multiple PDFs.",
    "extract_text": "Extract text from a selected page region.",
    "merge_sheet": "Combine CSV or Excel data files.",
    "barcode": "Generate a barcode or QR code.",
    "barcode_batch": "Read and report barcodes or QR codes from PDF files.",
    "encrypt": "Protect the current PDF with password security.",
    "decrypt": "Remove password security from an authorized PDF.",
}


def _regroup_tools(sections):
    items = {
        item.key: replace(
            item,
            description=item.description or TOOL_DESCRIPTIONS.get(item.key, ""),
            search_aliases=title,
        )
        for _key, title, group in sections
        for item in group
    }
    assigned = [key for _key, _title, _icon, keys in CATEGORY_LAYOUT for key in keys]
    if len(assigned) != len(set(assigned)) or set(assigned) != set(items):
        raise ValueError("Every PDF tool must belong to exactly one navigation category.")
    return tuple(
        (key, title, tuple(items[item] for item in keys)) for key, title, _icon, keys in CATEGORY_LAYOUT
    )


class CollapsibleSection(QWidget):
    """An animated group; compact navigation uses a separate category rail."""

    def __init__(self, key: str, title: str, animations_enabled: bool, parent=None):
        super().__init__(parent)
        self.key = key
        self._animations_enabled = animations_enabled
        self._sidebar_collapsed = False
        self._filtering = False
        self._logical_expanded = bool(QSettings().value(f"sidebar/v2/section/{key}", False, bool))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(S.XXS)

        self.header = QToolButton()
        self.header.setObjectName("sidebarSectionButton")
        self.header.setText(title.replace("&", "&&"))
        self.header.setAccessibleName(f"{title} section")
        self.header.setAccessibleDescription("Expanded" if self._logical_expanded else "Collapsed")
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
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self._apply_initial_layout)
        self._layout_timer.start(0)

    @pyqtSlot()
    def _apply_initial_layout(self) -> None:
        self._apply_expanded(False)

    def add_button(self, button: QPushButton) -> None:
        self.body_layout.addWidget(button)

    def _header_clicked(self, checked: bool) -> None:
        self._logical_expanded = checked
        QSettings().setValue(f"sidebar/v2/section/{self.key}", checked)
        self.header.setAccessibleDescription("Expanded" if checked else "Collapsed")
        self._update_header_icon()
        self._apply_expanded(True)

    def _update_header_icon(self) -> None:
        self.header.setIcon(icon("chevron-down" if self._logical_expanded else "chevron-right", 14))

    def _natural_height(self) -> int:
        self.body.adjustSize()
        return max(0, self.body.sizeHint().height())

    def _should_expand(self) -> bool:
        return self._filtering or self._logical_expanded

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
            self._layout_timer.start(0)

    def set_animations_enabled(self, enabled: bool) -> None:
        self._animations_enabled = enabled
        if not enabled:
            self._apply_expanded(False)

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
        "smart_detection",
        "ocr",
        "pdf_to_word",
        "extract_text",
        "flatten",
        "font_preflight",
        "encrypt",
        "decrypt",
        "highlight",
        "underline",
        "strikeout",
        "squiggly",
        "line",
        "arrow",
        "ellipse",
        "polygon",
        "freetext_typewriter",
        "freetext_box",
        "freetext_callout",
        "note",
        "ink",
        "rect",
        "redact",
        "stamp",
        "signature",
        "image",
        "watermark",
        "font_inspect",
        "fill_form",
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
                ToolItem("sort", "Advanced Page Organizer", "layers", "visual_organize.png"),
                ToolItem("split", "Split PDF", "scissors", "Split.png"),
                ToolItem("rotate", "Rotate pages", "rotate-cw", "rotate_pages.png"),
                ToolItem("info", "Document information", "info", "info.png"),
                ToolItem(
                    "smart_detection",
                    "Smart Detection",
                    "scan-search",
                    "smart_detection.png",
                ),
            ),
        ),
        (
            "annotate",
            "Annotate",
            (
                ToolItem("font_inspect", "Inspect text font", "font-inspect"),
                ToolItem("highlight", "Highlight text", "highlighter"),
                ToolItem("underline", "Underline text", "underline"),
                ToolItem("strikeout", "Strikethrough text", "strikethrough"),
                ToolItem("squiggly", "Squiggly underline", "waves"),
                ToolItem("note", "Sticky note", "message-square"),
                ToolItem("ink", "Freehand drawing", "pen-line"),
                ToolItem("rect", "Rectangle", "square"),
                ToolItem("line", "Line", "line-tool"),
                ToolItem("arrow", "Arrow", "arrow-up-right"),
                ToolItem("ellipse", "Ellipse", "circle"),
                ToolItem("polygon", "Polygon", "pentagon"),
                ToolItem("freetext_typewriter", "Typewriter text", "text-cursor-input"),
                ToolItem("freetext_box", "Text box", "square-type"),
                ToolItem("freetext_callout", "Callout", "message-square-more"),
                ToolItem("redact", "Redact content", "eraser"),
                ToolItem("stamp", "Rubber stamp", "stamp"),
                ToolItem(
                    "signature",
                    "Signature image",
                    "signature",
                    description="Place a handwritten-signature image and adjust its position and size. This does not create a digital signature.",
                ),
                ToolItem(
                    "image",
                    "Insert image",
                    "image",
                    description="Insert a PNG/JPG; drag to move or resize, or enter exact position and dimensions.",
                ),
                ToolItem("watermark", "Add watermark", "watermark"),
            ),
        ),
        (
            "convert",
            "Conversion",
            (
                ToolItem(
                    "ocr",
                    "OCR",
                    "scan",
                    "OCR1.png",
                    CapabilityId.OCR,
                ),
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
                ToolItem("fill_form", "Fill PDF form", "file-text"),
                ToolItem("compare_pdf", "Compare PDFs", "files"),
                ToolItem("find_file", "Find and open PDF", "search", "search_pdf.png"),
                ToolItem(
                    "page_report",
                    "Page count report",
                    "table",
                    "PDF-report.png",
                    CapabilityId.SPREADSHEET,
                ),
                ToolItem(
                    "extract_text",
                    "Extract text region",
                    "file-text",
                    "Extract-text.png",
                ),
                ToolItem("merge", "Merge PDFs", "files", "Merge-PDF.png"),
                ToolItem("overlay", "PDF overlay", "layers", "overlay.png"),
                ToolItem("batch_print", "Batch print", "printer", "Batch_print.png"),
                ToolItem("compress", "Compress PDFs", "files", "compress.png"),
                ToolItem(
                    "pdf_production",
                    "PDF Production Tools",
                    "wrench",
                    description="Font Preflight / Safe Embed Fonts, Flatten PDF, PDF Repair / Production Normalise: analyze and save a new copy.",
                ),
                ToolItem("deep_search", "Deep search", "search", "deep_search.png"),
                ToolItem(
                    "merge_sheet",
                    "Merge CSV / Excel",
                    "table",
                    "merge_csv_excel.png",
                    CapabilityId.SPREADSHEET,
                ),
                ToolItem(
                    "barcode",
                    "Barcode / QR code",
                    "scan",
                    "qrcode.png",
                    CapabilityId.BARCODE,
                ),
                ToolItem(
                    "barcode_batch",
                    "Batch Read Barcode/QR Code",
                    "scan",
                    "batch_qrcode.png",
                    CapabilityId.BARCODE,
                ),
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

    SECTIONS = _regroup_tools(SECTIONS)
    DEFAULT_FAVOURITES = ("search", "deep_search", "merge", "extract", "pdf_production")
    MAX_FAVOURITES = 8
    # These remain selected while the PDF canvas is in the corresponding mode.
    PERSISTENT_TOOLS = (DOCUMENT_TOOLS | {"fill_form"}) - {
        "search",
        "insert",
        "delete",
        "extract",
        "order",
        "sort",
        "split",
        "info",
        "smart_detection",
        "ocr",
        "pdf_to_word",
        "extract_text",
        "flatten",
        "font_preflight",
        "encrypt",
        "decrypt",
        "watermark",
    }

    def __init__(self, collapsed: bool = False, animations_enabled: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("leftPanel")
        self._collapsed = collapsed
        self._animations_enabled = animations_enabled
        self._panel_width = D.SIDEBAR_W
        self._active_key: str | None = None
        self._document_available = False
        self._document_encrypted = False
        self._shortcut_hints = SHORTCUT_HINTS.copy()
        self._buttons: dict[str, ToolNavButton] = {}
        self._favourite_buttons: dict[str, ToolNavButton] = {}
        self._rail_buttons: dict[str, ToolNavButton] = {}
        self._popup: ToolPopup | None = None
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
        header_layout.setContentsMargins(4, 2, 0, 2)
        self._title = QLabel("Tools")
        self._title.setObjectName("sidebarTitle")
        header_layout.addWidget(self._title, 1)
        self._toggle = QToolButton()
        self._toggle.setObjectName("sidebarCollapseButton")
        self._toggle.setIconSize(QSize(18, 18))
        self._toggle.clicked.connect(lambda: self.set_collapsed(not self._collapsed))
        header_layout.addWidget(self._toggle)
        layout.addWidget(self._header)
        self._search = QLineEdit()
        self._search.setObjectName("sidebarSearch")
        self._search.setPlaceholderText("Search tools…")
        self._search.setAccessibleName("Search PDF tools")
        self._search.setClearButtonEnabled(True)
        self._search_action = self._search.addAction(
            icon("search", 16), QLineEdit.ActionPosition.LeadingPosition
        )
        self._search.textChanged.connect(self._filter_tools)
        self._search.installEventFilter(self)
        layout.addWidget(self._search)
        self._compact_search = ToolNavButton("Search tools")
        self._compact_search.setObjectName("sidebarNavButton")
        self._compact_search.setIcon(icon("search", 22))
        self._compact_search.setToolTip("Search all PDF tools")
        self._compact_search.set_compact(True)
        self._compact_search.set_animations_enabled(self._animations_enabled)
        self._compact_search.clicked.connect(lambda: self._open_popup(None, self._compact_search))
        layout.addWidget(self._compact_search)
        self._scroll = QScrollArea()
        self._scroll.setObjectName("sidebarScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("sidebarContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, S.SM)
        content_layout.setSpacing(S.XS)
        self._favourites = QWidget()
        favourites_layout = QVBoxLayout(self._favourites)
        favourites_layout.setContentsMargins(0, 0, 0, 0)
        favourites_layout.setSpacing(2)
        self._favourites_header = QWidget()
        heading = QHBoxLayout(self._favourites_header)
        heading.setContentsMargins(8, 0, 0, 0)
        heading.addWidget(QLabel("Favourites"), 1)
        self._edit_favourites = QToolButton()
        self._edit_favourites.setText("Edit")
        self._edit_favourites.setToolTip("Choose and reorder favourite tools")
        self._edit_favourites.clicked.connect(self._configure_favourites)
        heading.addWidget(self._edit_favourites)
        favourites_layout.addWidget(self._favourites_header)
        self._favourites_body = QVBoxLayout()
        self._favourites_body.setContentsMargins(0, 0, 0, 0)
        self._favourites_body.setSpacing(2)
        favourites_layout.addLayout(self._favourites_body)
        content_layout.addWidget(self._favourites)
        self._divider = QFrame()
        self._divider.setObjectName("sidebarDivider")
        self._divider.setFrameShape(QFrame.Shape.HLine)
        content_layout.addWidget(self._divider)
        self._tool_count = QLabel("No matching tools")
        self._tool_count.setWordWrap(True)
        content_layout.addWidget(self._tool_count)
        self._tool_count.hide()
        for section_key, title, items in self.SECTIONS:
            section = CollapsibleSection(section_key, title, self._animations_enabled)
            for item in items:
                button = ToolNavButton(item.label)
                button.setObjectName("sidebarNavButton")
                button.setCheckable(True)
                button.setProperty("section", section_key)
                button.setIcon(self._item_icon(item))
                button.set_animations_enabled(self._animations_enabled)
                button.clicked.connect(lambda _=False, key=item.key: self._activate_and_emit(key))
                button.installEventFilter(self)
                button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                button.customContextMenuRequested.connect(
                    lambda point, key=item.key: self._pin_menu(key, point)
                )
                section.add_button(button)
                self._buttons[item.key] = button
                self._items[item.key] = item
            content_layout.addWidget(section)
            self._sections.append(section)
        self._rail = QWidget()
        rail_layout = QVBoxLayout(self._rail)
        rail_layout.setContentsMargins(0, 0, 0, 0)
        rail_layout.setSpacing(4)
        for key, title, image, _keys in CATEGORY_LAYOUT:
            button = ToolNavButton(title)
            button.setObjectName("sidebarNavButton")
            button.setIcon(icon(image, 22))
            button.setToolTip(title)
            button.set_compact(True)
            button.set_animations_enabled(self._animations_enabled)
            button.clicked.connect(
                lambda _=False, category=key, anchor=button: self._open_popup(category, anchor)
            )
            rail_layout.addWidget(button)
            self._rail_buttons[key] = button
        content_layout.addWidget(self._rail)
        content_layout.addStretch(1)
        self._scroll.setWidget(content)
        layout.addWidget(self._scroll, 1)
        stored = QSettings().value("sidebar/v2/favourites", None)
        self.set_favourites(self.DEFAULT_FAVOURITES if stored is None else stored, persist=False)
        self._refresh_availability()

    def set_favourites(self, keys, *, persist=True):
        if not isinstance(keys, (tuple, list)):
            keys = self.DEFAULT_FAVOURITES
        valid = list(dict.fromkeys(key for key in keys if isinstance(key, str) and key in self._items))[
            : self.MAX_FAVOURITES
        ]
        self._favourite_keys = valid
        while self._favourites_body.count():
            widget = self._favourites_body.takeAt(0).widget()
            widget.hide()
            widget.deleteLater()
        self._favourite_buttons.clear()
        for key in valid:
            button = ToolNavButton(self._items[key].label)
            button.setObjectName("sidebarNavButton")
            button.setCheckable(True)
            button.set_compact(self._collapsed)
            button.set_animations_enabled(self._animations_enabled)
            button.clicked.connect(lambda _=False, key=key: self._activate_and_emit(key))
            self._favourites_body.addWidget(button)
            self._favourite_buttons[key] = button
        if persist:
            QSettings().setValue("sidebar/v2/favourites", valid)
        self._sync_views()
        self._favourites.setVisible(
            (self._collapsed or not self._search.text().strip()) and (bool(valid) or not self._collapsed)
        )
        self._divider.setVisible(bool(valid) and (self._collapsed or not self._search.text().strip()))

    def _configure_favourites(self):
        dialog = FavouritesDialog(self._items, self._favourite_keys, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_favourites(dialog.keys())
        dialog.deleteLater()

    def _pin_menu(self, key, point):
        menu = QMenu(self)
        pinned = key in self._favourite_keys
        action = menu.addAction("Remove from favourites" if pinned else "Add to favourites")
        action.setEnabled(pinned or len(self._favourite_keys) < self.MAX_FAVOURITES)
        if not action.isEnabled():
            action.setText("Favourites full (8) — use Edit")
        if menu.exec(self._buttons[key].mapToGlobal(point)) is action:
            self.set_favourites(
                [item for item in self._favourite_keys if item != key]
                if pinned
                else [*self._favourite_keys, key]
            )
        menu.deleteLater()

    def _sync_views(self):
        for key, button in self._favourite_buttons.items():
            source = self._buttons[key]
            button.setIcon(source.icon())
            button.setEnabled(source.isEnabled())
            button.setToolTip(source.toolTip())
            button.setAccessibleDescription(source.toolTip())
            button.setChecked(source.isChecked())
            button.setProperty("active", source.property("active"))
            button.style().unpolish(button)
            button.style().polish(button)
        for category, _title, items in self.SECTIONS:
            active = any(item.key == self._active_key for item in items)
            self._rail_buttons[category].setProperty("active", active)
            self._rail_buttons[category].style().unpolish(self._rail_buttons[category])
            self._rail_buttons[category].style().polish(self._rail_buttons[category])
        if self._popup is not None:
            self._popup.refresh()

    def _open_popup(self, category, anchor):
        if self._popup is not None:
            self._popup.hide()
            self._popup.deleteLater()
        title = "All PDF tools"
        entries = list(self._items.values())
        if category is not None:
            _key, title, items = next(section for section in self.SECTIONS if section[0] == category)
            entries = list(items)
        self._popup = ToolPopup(title, entries, self._buttons, self._matches, self)
        self._popup.toolRequested.connect(self._activate_and_emit)
        self._popup.open_at(anchor)

    def _matches(self, key, query):
        query = query.strip().casefold()
        if not query:
            return True
        item = self._items[key]
        category = next(title for _key, title, items in self.SECTIONS if item in items)
        text = " ".join(
            (
                item.label,
                category,
                item.description,
                item.search_aliases,
                SEARCH_ALIASES.get(key, ""),
                self._shortcut_hints.get(key, ""),
            )
        ).casefold()
        return all(term in text for term in query.split())

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            if watched is self._search and event.key() == Qt.Key.Key_Escape:
                self._search.clear()
                return True
            choices = [
                button for button in self._buttons.values() if button.isVisible() and button.isEnabled()
            ]
            if (watched is self._search or watched in choices) and choices:
                if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                    step = 1 if event.key() == Qt.Key.Key_Down else -1
                    index = choices.index(watched) if watched in choices else (-1 if step == 1 else 0)
                    button = choices[(index + step) % len(choices)]
                    button.setFocus()
                    self._scroll.ensureWidgetVisible(button)
                    return True
                if watched is self._search and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    choices[0].click()
                    return True
        return super().eventFilter(watched, event)

    def _item_icon(self, item: ToolItem):
        return app_icon(item.asset_name, 24) if item.asset_name else icon(item.icon_name, 22)

    def _activate_and_emit(self, key: str) -> None:
        if not self._buttons[key].isEnabled():
            return
        if key in self.PERSISTENT_TOOLS:
            self.set_active_tool(key)
        else:
            # Dialog actions don't replace the canvas's active editing mode.
            self.set_active_tool(self._active_key)
        if key in self._favourite_buttons:
            self._favourite_buttons[key].animate_click()
        else:
            self._buttons[key].animate_click()
        self.toolRequested.emit(key)

    def _filter_tools(self, value: str) -> None:
        query = value.strip()
        count = 0
        for section, (_key, _title, items) in zip(self._sections, self.SECTIONS, strict=True):
            matches = 0
            for item in items:
                visible = self._matches(item.key, query)
                self._buttons[item.key].setVisible(visible)
                matches += int(visible)
            count += matches
            section.set_filtering(bool(query), matches > 0)
            if self._collapsed:
                section.hide()
        self._favourites.setVisible(
            (self._collapsed or not query) and (bool(self._favourite_keys) or not self._collapsed)
        )
        self._divider.setVisible((self._collapsed or not query) and bool(self._favourite_keys))
        self._tool_count.setVisible(bool(query) and count == 0 and not self._collapsed)

    def set_collapsed(self, collapsed: bool, animate: bool = True) -> None:
        self._collapsed = collapsed
        target = D.SIDEBAR_COLLAPSED_W if collapsed else D.SIDEBAR_W
        if self._popup is not None:
            self._popup.hide()
        self._title.setVisible(not collapsed)
        self._compact_search.setVisible(collapsed)
        self._rail.setVisible(collapsed)
        self._favourites_header.setVisible(not collapsed)
        self._search.setVisible(not collapsed)
        self._toggle.setIcon(icon("chevron-right" if collapsed else "chevron-left", 18))
        self._toggle.setToolTip("Expand tools" if collapsed else "Collapse tools")
        self._toggle.setAccessibleName("Expand tool navigation" if collapsed else "Collapse tool navigation")
        for section in self._sections:
            section.set_sidebar_collapsed(collapsed)
        for button in (*self._buttons.values(), *self._favourite_buttons.values()):
            button.set_compact(collapsed)
            button.style().unpolish(button)
            button.style().polish(button)
        self._filter_tools(self._search.text())
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
        for button in (
            *self._buttons.values(),
            *self._favourite_buttons.values(),
            *self._rail_buttons.values(),
        ):
            button.set_animations_enabled(enabled)
        self._compact_search.set_animations_enabled(enabled)
        if not enabled:
            self._width_animation.stop()
            self._finish_width_animation()

    def _base_tooltip(self, key: str) -> str:
        item = self._items[key]
        hint = self._shortcut_hints.get(key, "")
        text = f"{item.label} ({hint})" if hint else item.label
        return f"{text}\n{item.description}" if item.description else text

    def set_shortcut_hints(self, hints: dict[str, str]) -> None:
        self._shortcut_hints = {key: value for key, value in hints.items() if key in self._items and value}
        self._refresh_availability()
        self._filter_tools(self._search.text())
        if self._popup is not None:
            self._popup.filter_tools(self._popup.search.text())

    def refresh_capabilities(self) -> None:
        self._refresh_availability()

    def set_document_available(
        self,
        available: bool,
        encrypted: bool = False,
        *,
        unavailable_hint: str = "Open a PDF to use this tool.",
    ) -> None:
        self._document_available = available
        self._document_encrypted = encrypted
        self._document_unavailable_hint = unavailable_hint
        self._refresh_availability()

    def _refresh_availability(self) -> None:
        capabilities = detect_capabilities()
        for key, item in self._items.items():
            button = self._buttons[key]
            button.setToolTip(self._base_tooltip(key))
            if key in self.DOCUMENT_TOOLS and not self._document_available:
                button.setEnabled(False)
                button.setToolTip(
                    f"{self._base_tooltip(key)}\n{getattr(self, '_document_unavailable_hint', 'Open a PDF to use this tool.')}"
                )
                continue
            if key == "decrypt" and not self._document_encrypted:
                button.setEnabled(False)
                button.setToolTip(f"{self._base_tooltip(key)}\nThe open PDF has no password security.")
                continue
            if item.capability is not None:
                capability = capabilities[item.capability]
                button.setEnabled(capability.available)
                if not capability.available:
                    button.setToolTip(
                        f"{self._base_tooltip(key)}\nUnavailable: {capability.reason}\n{capability.guidance}"
                    )
                continue
            button.setEnabled(True)
        for button in self._buttons.values():
            button.setAccessibleDescription(button.toolTip())
        self._sync_views()

    def set_active_tool(self, key: str | None) -> None:
        self._active_key = key if key in self.PERSISTENT_TOOLS else None
        for item_key, button in self._buttons.items():
            active = item_key == self._active_key
            button.setChecked(active)
            button.setProperty("active", active)
            button.style().unpolish(button)
            button.style().polish(button)

        self._sync_views()

    def refresh_icons(self) -> None:
        self._toggle.setIcon(icon("chevron-right" if self._collapsed else "chevron-left", 18))
        self._search_action.setIcon(icon("search", 16))
        for section in self._sections:
            section.refresh_icon()
        for key, item in self._items.items():
            self._buttons[key].setIcon(self._item_icon(item))
        self._compact_search.setIcon(icon("search", 22))
        for key, _title, image, _keys in CATEGORY_LAYOUT:
            self._rail_buttons[key].setIcon(icon(image, 22))
        self._sync_views()
