"""Right-hand contextual page-operation and annotation panel."""

from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QSettings,
    QSignalBlocker,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QFontDatabase
from PyQt6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QCompleter,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.annotations import STAMP_IDS
from core.pdf_engine import parse_page_range
from styles.tokens import D, S

from .motion import MotionIconButton

SWATCHES: dict[str, str] = {
    "yellow": "#ffd54a",
    "green": "#81c784",
    "cyan": "#4dd0e1",
    "pink": "#f48fb1",
    "orange": "#ffb74d",
    "red": "#e57373",
}


class ContextPanel(QFrame):
    closed = pyqtSignal()
    rotateRequested = pyqtSignal(str, int)
    deleteRequested = pyqtSignal(str)
    extractRequested = pyqtSignal(str)
    splitRequested = pyqtSignal(int)
    insertRequested = pyqtSignal(str, str, int)
    orderRequested = pyqtSignal(str)
    annotationColorChanged = pyqtSignal(str)
    annotationWidthChanged = pyqtSignal(float)
    stampKindChanged = pyqtSignal(str)
    stampImageChanged = pyqtSignal(str)
    customStampAddRequested = pyqtSignal()
    customTextStampAddRequested = pyqtSignal()
    customStampRemoveRequested = pyqtSignal(str)
    annotationStyleChanged = pyqtSignal(object)
    editAnnotationRequested = pyqtSignal(int, int, object)
    imagePathChanged = pyqtSignal(str)
    removeAnnotationRequested = pyqtSignal(int, int)
    annotationSelected = pyqtSignal(int, int)
    applyRedactionsRequested = pyqtSignal()
    exportAnnotationsRequested = pyqtSignal()
    importAnnotationsRequested = pyqtSignal()
    exportAnnotationSummaryRequested = pyqtSignal()
    flattenAnnotationsRequested = pyqtSignal()
    fontStyleApplyRequested = pyqtSignal(str, object)
    fontNameCopyRequested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("contextPanel")
        self._panel_width = 0
        self._page_count = 0
        self._animations_enabled = True
        self._closing = False
        self.setMinimumWidth(0)
        self.setMaximumWidth(0)
        self._width_animation = QPropertyAnimation(self, b"panelWidth", self)
        self._width_animation.setDuration(180)
        self._width_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._width_animation.finished.connect(self._animation_finished)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(S.LG, S.MD, S.LG, S.LG)
        layout.setSpacing(S.MD)

        header = QHBoxLayout()
        self._title = QLabel("Options")
        self._title.setObjectName("appTitle")
        header.addWidget(self._title)
        header.addStretch(1)
        self._close = MotionIconButton("x", "Close options", D.ICON_SM)
        self._close.clicked.connect(self.closed.emit)
        header.addWidget(self._close)
        layout.addLayout(header)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack, 1)
        self._pages: dict[str, QWidget] = {}
        self._build_rotate()
        self._build_ranges("delete", "Delete Pages", self.deleteRequested)
        self._build_ranges("extract", "Extract Pages", self.extractRequested)
        self._build_split()
        self._build_insert()
        self._build_order()
        self._build_annotate()
        self._build_font_inspector()

    @pyqtProperty(int)
    def panelWidth(self) -> int:  # noqa: N802 - Qt property naming
        return self._panel_width

    @panelWidth.setter
    def panelWidth(self, value: int) -> None:  # noqa: N802 - Qt property naming
        value = max(0, value)
        self._panel_width = value
        self.setMinimumWidth(value)
        self.setMaximumWidth(value)
        splitter = self.parentWidget()
        if isinstance(splitter, QSplitter):
            sizes = splitter.sizes()
            if len(sizes) >= 3:
                total = sum(sizes)
                left = sizes[0]
                sizes[2] = value
                sizes[1] = max(0, total - left - value)
                splitter.setSizes(sizes)

    def _add_page(self, key: str, page: QWidget) -> None:
        self._pages[key] = page
        self._stack.addWidget(page)

    def _base_page(self, description: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setObjectName("contextPage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(S.SM, S.SM, S.SM, S.SM)
        description_label = QLabel(description)
        description_label.setObjectName("secondary")
        description_label.setWordWrap(True)
        layout.addWidget(description_label)
        return page, layout

    def _build_rotate(self) -> None:
        page, layout = self._base_page("Rotate the current page, a page range, or the whole document.")
        form = QFormLayout()
        pages = QLineEdit()
        pages.setPlaceholderText("Current, all, or 1,3,5-8")
        pages.textChanged.connect(lambda text: self._validate_pages_input(pages, text, allow_empty=True))
        angle = QComboBox()
        angle.addItems(["90° clockwise", "180°", "90° counter-clockwise"])
        angle.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow)
        angle.setToolTip("Rotation angle to apply to selected pages")
        form.addRow("Pages", pages)
        form.addRow("Angle", angle)
        layout.addLayout(form)
        self._add_quick_buttons(layout, pages)
        self._validation_rotate = self._add_validation_label(layout)
        apply = QPushButton("Rotate")
        apply.setProperty("primary", True)
        apply.clicked.connect(lambda: self.rotateRequested.emit(pages.text().strip(), (90, 180, -90)[angle.currentIndex()]))
        layout.addWidget(apply)
        layout.addStretch(1)
        page.pages_edit = pages  # type: ignore[attr-defined]
        self._add_page("rotate", page)

    def _build_ranges(self, key: str, action: str, signal) -> None:
        page, layout = self._base_page(f"{action} using one-based page numbers and ranges.")
        pages = QLineEdit()
        pages.setPlaceholderText("e.g. 1,3,5-8")
        pages.textChanged.connect(lambda text: self._validate_pages_input(pages, text))
        layout.addWidget(QLabel("Pages"))
        layout.addWidget(pages)
        self._add_quick_buttons(layout, pages)
        validation_label = self._add_validation_label(layout)
        apply = QPushButton(action)
        apply.setProperty("primary", True)
        apply.clicked.connect(lambda: signal.emit(pages.text().strip()))
        layout.addWidget(apply)
        layout.addStretch(1)
        page.pages_edit = pages  # type: ignore[attr-defined]
        page.validation_label = validation_label  # type: ignore[attr-defined]
        self._add_page(key, page)

    def _build_split(self) -> None:
        page, layout = self._base_page("Create a new PDF after every selected number of pages.")
        every = QSpinBox()
        every.setRange(1, 9999)
        every.setValue(1)
        layout.addWidget(QLabel("Pages per file"))
        layout.addWidget(every)
        apply = QPushButton("Split PDF")
        apply.setProperty("primary", True)
        apply.clicked.connect(lambda: self.splitRequested.emit(every.value()))
        layout.addWidget(apply)
        layout.addStretch(1)
        self._add_page("split", page)

    def _build_insert(self) -> None:
        page, layout = self._base_page("Insert pages from another PDF into this document.")
        form = QFormLayout()
        source = QLineEdit()
        source.setReadOnly(True)
        browse = QPushButton("Choose PDF…")
        browse.setProperty("secondary", True)
        browse.clicked.connect(lambda: self.insertRequested.emit("browse", source.text(), position.value()))
        position = QSpinBox()
        position.setMinimum(1)
        form.addRow("Source", source)
        form.addRow("", browse)
        form.addRow("Insert before page", position)
        layout.addLayout(form)
        apply = QPushButton("Insert all pages")
        apply.setProperty("primary", True)
        apply.clicked.connect(lambda: self.insertRequested.emit("apply", source.text(), position.value()))
        layout.addWidget(apply)
        layout.addStretch(1)
        page.source_edit = source  # type: ignore[attr-defined]
        page.position_spin = position  # type: ignore[attr-defined]
        self._add_page("insert", page)

    def _build_order(self) -> None:
        page, layout = self._base_page("Reorder all pages. Enter each page exactly once.")
        order = QLineEdit()
        order.setPlaceholderText("e.g. 3,1,2,4")
        layout.addWidget(QLabel("New page order"))
        layout.addWidget(order)
        reverse = QPushButton("Reverse all pages")
        reverse.setProperty("secondary", True)
        reverse.clicked.connect(lambda: self.orderRequested.emit("reverse"))
        apply = QPushButton("Apply order")
        apply.setProperty("primary", True)
        apply.clicked.connect(lambda: self.orderRequested.emit(order.text().strip()))
        layout.addWidget(reverse)
        layout.addWidget(apply)
        layout.addStretch(1)
        self._add_page("sort", page)

    def _build_annotate(self) -> None:
        page, outer_layout = self._base_page(
            "Create annotations and manage every annotation in this document."
        )
        self._annot_tabs = QTabWidget()
        self._annot_tabs.setObjectName("annotationTabs")
        outer_layout.addWidget(self._annot_tabs, 1)

        create_scroll = QScrollArea()
        create_scroll.setWidgetResizable(True)
        create_scroll.setFrameShape(QFrame.Shape.NoFrame)
        create_page = QWidget()
        layout = QVBoxLayout(create_page)
        layout.setContentsMargins(S.XS, S.SM, S.XS, S.SM)
        layout.setSpacing(S.MD)
        create_scroll.setWidget(create_page)
        self._annot_tabs.addTab(create_scroll, "Create")

        self._active_tool_title = QLabel("Annotation tool")
        self._active_tool_title.setObjectName("sectionTitle")
        layout.addWidget(self._active_tool_title)
        self._active_tool_hint = QLabel(
            "Choose a tool on the left, then drag directly on the PDF page."
        )
        self._active_tool_hint.setObjectName("secondary")
        self._active_tool_hint.setWordWrap(True)
        layout.addWidget(self._active_tool_hint)
        self._current_color = "yellow"
        self._current_fill = ""
        self._annot_color_label = QLabel("Stroke / text color")
        self._annot_color_label.setObjectName("sectionTitle")
        layout.addWidget(self._annot_color_label)
        colors_row = QHBoxLayout()
        colors_row.setSpacing(S.XS)
        self._color_buttons: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for key, hex_value in SWATCHES.items():
            button = QPushButton()
            button.setObjectName("swatchButton")
            button.setCheckable(True)
            button.setFixedSize(32, 32)
            button.setToolTip(key.title())
            button.setAccessibleName(f"Annotation color {key}")
            button.setStyleSheet(
                f"QPushButton#swatchButton {{ background: {hex_value};"
                f" border: 2px solid transparent; border-radius: 16px; }}"
                f"QPushButton#swatchButton:checked {{ border: 3px solid #202124; }}"
            )
            button.clicked.connect(
                lambda _checked=False, value=key: self._set_annotation_color(value)
            )
            group.addButton(button)
            colors_row.addWidget(button)
            self._color_buttons[key] = button
        colors_row.addStretch(1)
        self._custom_color = QPushButton("Custom…")
        self._custom_color.clicked.connect(self._choose_custom_color)
        self._fill_color = QPushButton("Fill…")
        self._fill_color.clicked.connect(self._choose_fill_color)
        self._clear_fill = QPushButton("Clear fill")
        self._clear_fill.setProperty("secondary", True)
        self._clear_fill.clicked.connect(self._clear_fill_color)

        layout.addLayout(colors_row)
        color_actions = QHBoxLayout()
        color_actions.addWidget(self._custom_color)
        color_actions.addWidget(self._fill_color)
        color_actions.addWidget(self._clear_fill)
        color_actions.addStretch(1)
        layout.addLayout(color_actions)
        self._color_buttons["yellow"].setChecked(True)

        color_summary = QVBoxLayout()
        self._stroke_value = QLabel("Text/stroke: yellow")
        self._fill_value = QLabel("Background: transparent")
        self._stroke_value.setObjectName("secondary")
        self._fill_value.setObjectName("secondary")
        color_summary.addWidget(self._stroke_value)
        color_summary.addWidget(self._fill_value)
        layout.addLayout(color_summary)
        self._contrast_status = QLabel()
        self._contrast_status.setWordWrap(True)
        layout.addWidget(self._contrast_status)

        width_row = QHBoxLayout()
        self._annot_width_label = QLabel("Line width")
        width_row.addWidget(self._annot_width_label)
        self._annot_width = QDoubleSpinBox()
        self._annot_width.setRange(0.5, 20.0)
        self._annot_width.setSingleStep(0.5)
        self._annot_width.setDecimals(1)
        self._annot_width.setValue(1.5)
        self._annot_width.valueChanged.connect(self.annotationWidthChanged.emit)
        self._annot_width.valueChanged.connect(self._emit_annotation_style)
        width_row.addWidget(self._annot_width)
        width_row.addStretch(1)
        layout.addLayout(width_row)
        self._style_form = QFormLayout()
        self._annot_opacity = QSpinBox()
        self._annot_opacity.setRange(5, 100)
        self._annot_opacity.setSuffix(" %")
        self._annot_opacity.setValue(100)
        self._annot_opacity.valueChanged.connect(self._emit_annotation_style)
        self._style_form.addRow("Opacity", self._annot_opacity)
        self._annot_font = QComboBox()
        self._annot_font.addItems(["Helv", "Cour", "Times-Roman"])
        self._annot_font.insertSeparator(self._annot_font.count())
        for family in QFontDatabase.families():
            if not QFontDatabase.isSmoothlyScalable(family):
                continue
            if self._annot_font.findText(family, Qt.MatchFlag.MatchFixedString) >= 0:
                continue
            self._annot_font.addItem(family)
            self._annot_font.setItemData(
                self._annot_font.count() - 1,
                QFont(family),
                Qt.ItemDataRole.FontRole,
            )
        self._annot_font.setEditable(True)
        self._annot_font.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._annot_font.setMaxVisibleItems(18)
        font_completer = QCompleter(self._annot_font.model(), self._annot_font)
        font_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        font_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        font_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._annot_font.setCompleter(font_completer)
        self._annot_font.setToolTip(
            "PDF built-in fonts are portable; installed system fonts are embedded "
            "in new text annotations. Type to search."
        )
        self._annot_font.currentTextChanged.connect(self._emit_annotation_style)
        self._style_form.addRow("Font", self._annot_font)
        self._annot_font_size = QSpinBox()
        self._annot_font_size.setRange(4, 144)
        self._annot_font_size.setValue(11)
        self._annot_font_size.valueChanged.connect(self._emit_annotation_style)
        self._style_form.addRow("Font size", self._annot_font_size)
        self._annot_alignment = QComboBox()
        self._annot_alignment.addItem("Left", 0)
        self._annot_alignment.addItem("Center", 1)
        self._annot_alignment.addItem("Right", 2)
        self._annot_alignment.currentIndexChanged.connect(self._emit_annotation_style)
        self._style_form.addRow("Alignment", self._annot_alignment)
        layout.addLayout(self._style_form)


        stamp_form = QFormLayout()
        self._stamp_kind = QComboBox()
        for name in STAMP_IDS:
            self._stamp_kind.addItem(name)
        self._stamp_kind.setCurrentText("Draft")
        self._stamp_kind.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow
        )
        self._stamp_kind.currentIndexChanged.connect(self._stamp_selection_changed)
        self._stamp_label = QLabel("Stamp")
        stamp_form.addRow(self._stamp_label, self._stamp_kind)
        layout.addLayout(stamp_form)
        self._stamp_actions = QWidget()
        stamp_actions = QHBoxLayout(self._stamp_actions)
        stamp_actions.setContentsMargins(0, 0, 0, 0)
        self._stamp_add = QPushButton("Add image…")
        self._stamp_add.setProperty("secondary", True)
        self._stamp_add.clicked.connect(self.customStampAddRequested.emit)
        self._stamp_add_text = QPushButton("Add text…")
        self._stamp_add_text.setProperty("secondary", True)
        self._stamp_add_text.clicked.connect(self.customTextStampAddRequested.emit)
        self._stamp_remove = QPushButton("Remove")
        self._stamp_remove.setProperty("secondary", True)
        self._stamp_remove.setEnabled(False)
        self._stamp_remove.clicked.connect(self._remove_current_custom_stamp)
        stamp_actions.addWidget(self._stamp_add)
        stamp_actions.addWidget(self._stamp_add_text)
        stamp_actions.addWidget(self._stamp_remove)
        layout.addWidget(self._stamp_actions)

        self._image_label = QLabel("Signature / Image source")
        layout.addWidget(self._image_label)
        image_row = QHBoxLayout()
        self._image_edit = QLineEdit()
        self._image_edit.setReadOnly(True)
        self._image_edit.setPlaceholderText("Choose a PNG or JPG")
        self._image_browse = QPushButton("Browse…")
        self._image_browse.clicked.connect(self._browse_image)
        image_row.addWidget(self._image_edit, 1)
        image_row.addWidget(self._image_browse)
        layout.addLayout(image_row)

        layout.addStretch(1)

        manage_scroll = QScrollArea()
        manage_scroll.setWidgetResizable(True)
        manage_scroll.setFrameShape(QFrame.Shape.NoFrame)
        manage_page = QWidget()
        layout = QVBoxLayout(manage_page)
        layout.setContentsMargins(S.XS, S.SM, S.XS, S.SM)
        layout.setSpacing(S.MD)
        manage_scroll.setWidget(manage_page)
        self._annot_tabs.addTab(manage_scroll, "Manage")

        layout.addWidget(QLabel("Document annotations"))
        list_filters = QHBoxLayout()
        self._annot_search = QLineEdit()
        self._annot_search.setPlaceholderText("Search content, author, type…")
        self._annot_search.setClearButtonEnabled(True)
        self._annot_search.textChanged.connect(self._filter_annotations)
        self._annot_type_filter = QComboBox()
        self._annot_type_filter.addItem("All types", "")
        self._annot_type_filter.currentIndexChanged.connect(self._filter_annotations)
        list_filters.addWidget(self._annot_search, 1)
        list_filters.addWidget(self._annot_type_filter)
        layout.addLayout(list_filters)
        self._annot_list = QListWidget()
        self._annot_list.setObjectName("navList")
        layout.addWidget(self._annot_list, 1)
        self._annot_list.currentItemChanged.connect(
            self._load_selected_annotation
        )
        self._annot_list.itemActivated.connect(self._emit_annotation_selected)
        properties = QFormLayout()
        self._properties_form = properties
        self._property_text = QPlainTextEdit()
        self._property_text.setPlaceholderText("FreeText / note content")
        self._property_text.setFixedHeight(84)
        properties.addRow("Content", self._property_text)
        layout.addLayout(properties)
        self._set_content_editor_visible(False)
        self._apply_properties = QPushButton("Apply Style")
        self._apply_properties.setProperty("secondary", True)
        self._apply_properties.setEnabled(False)
        self._apply_properties.clicked.connect(self._apply_selected_annotation)
        layout.addWidget(self._apply_properties)

        actions = QHBoxLayout()
        self._remove_selected = QPushButton("Remove Selected")
        self._remove_selected.setProperty("secondary", True)
        self._remove_selected.setEnabled(False)
        self._remove_selected.clicked.connect(self._remove_selected_annotation)
        actions.addWidget(self._remove_selected)
        layout.addLayout(actions)
        apply_redactions = QPushButton("Apply Redaction Marks…")
        apply_redactions.setProperty("danger", True)
        apply_redactions.clicked.connect(self.applyRedactionsRequested.emit)
        layout.addWidget(apply_redactions)
        interchange = QHBoxLayout()
        export_json = QPushButton("Export JSON…")
        import_json = QPushButton("Import JSON…")
        export_json.clicked.connect(self.exportAnnotationsRequested.emit)
        import_json.clicked.connect(self.importAnnotationsRequested.emit)
        interchange.addWidget(export_json)
        interchange.addWidget(import_json)
        layout.addLayout(interchange)
        outputs = QHBoxLayout()
        summary = QPushButton("Summary…")
        flatten = QPushButton("Flatten Copy…")
        summary.clicked.connect(self.exportAnnotationSummaryRequested.emit)
        flatten.clicked.connect(self.flattenAnnotationsRequested.emit)
        outputs.addWidget(summary)
        outputs.addWidget(flatten)
        layout.addLayout(outputs)
        layout.addStretch(1)
        self._add_page("annotate", page)

    def _build_font_inspector(self) -> None:
        page, layout = self._base_page(
            "Select this tool, then click text on the PDF to inspect its font span."
        )
        self._font_inspector_status = QLabel(
            "Click text on the page to inspect its font."
        )
        self._font_inspector_status.setObjectName("pageRangeStatus")
        self._font_inspector_status.setWordWrap(True)
        layout.addWidget(self._font_inspector_status)

        self._font_sample = QLabel("Aa  Sample text")
        self._font_sample.setObjectName("fontInspectorSample")
        self._font_sample.setWordWrap(True)
        self._font_sample.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self._font_sample)

        form = QFormLayout()
        self._font_inspector_values: dict[str, QLabel] = {}
        for key, title in (
            ("text", "Text span"),
            ("raw_font", "PDF font"),
            ("display_font", "Readable name"),
            ("suggested_font", "Reusable font"),
            ("size", "Font size"),
            ("color", "Text color"),
            ("styles", "Style"),
            ("resource", "PDF resource"),
            ("encoding", "Encoding"),
            ("embedded", "Embedding"),
            ("page", "Page"),
        ):
            value = QLabel("—")
            value.setWordWrap(True)
            value.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            if key == "color":
                value.setObjectName("fontInspectorColor")
            form.addRow(title, value)
            self._font_inspector_values[key] = value
        layout.addLayout(form)

        self._font_apply_typewriter = QPushButton("Use for Typewriter")
        self._font_apply_typewriter.setProperty("primary", True)
        self._font_apply_typewriter.clicked.connect(
            lambda: self._apply_inspected_font("freetext_typewriter")
        )
        self._font_apply_box = QPushButton("Use for Text Box")
        self._font_apply_box.setProperty("secondary", True)
        self._font_apply_box.clicked.connect(
            lambda: self._apply_inspected_font("freetext_box")
        )
        apply_row = QHBoxLayout()
        apply_row.addWidget(self._font_apply_typewriter)
        apply_row.addWidget(self._font_apply_box)
        layout.addLayout(apply_row)

        self._font_copy_name = QPushButton("Copy font name")
        self._font_copy_name.setProperty("secondary", True)
        self._font_copy_name.clicked.connect(self._copy_inspected_font_name)
        layout.addWidget(self._font_copy_name)
        layout.addStretch(1)
        self._font_inspection: dict[str, object] | None = None
        self.set_font_inspection(None)
        self._add_page("font_inspect", page)

    def set_font_inspection(
        self, inspection: dict[str, object] | None, *, no_hit: bool = False
    ) -> None:
        self._font_inspection = dict(inspection) if inspection else None
        if not inspection:
            message = (
                "No text font was found here. The content may be an image, "
                "vector outlines, or whitespace."
                if no_hit
                else "Click text on the page to inspect its font."
            )
            self._font_inspector_status.setText(message)
            self._font_inspector_status.setObjectName(
                "validationError" if no_hit else "pageRangeStatus"
            )
            for value in self._font_inspector_values.values():
                value.setText("—")
                value.setStyleSheet("")
            self._font_sample.setText("Aa  Sample text")
            self._font_sample.setFont(QFont())
            self._font_apply_typewriter.setEnabled(False)
            self._font_apply_box.setEnabled(False)
            self._font_copy_name.setEnabled(False)
            self._refresh_font_inspector_status_style()
            return

        styles = inspection.get("styles") or []
        style_text = ", ".join(str(item) for item in styles) or "Regular"
        embedded = "Embedded" if inspection.get("embedded") else "Not embedded"
        if inspection.get("subset"):
            embedded += " · subset"
        xref = int(inspection.get("xref") or 0)
        resource = str(inspection.get("font_type") or "Unknown")
        if xref:
            resource += f" · xref {xref}"
        values = {
            "text": str(inspection.get("text") or "—"),
            "raw_font": str(inspection.get("raw_font") or "—"),
            "display_font": str(inspection.get("display_font") or "—"),
            "suggested_font": str(inspection.get("suggested_font") or "—"),
            "size": f"{float(inspection.get('size') or 0.0):.2f} pt",
            "color": str(inspection.get("color") or "#000000"),
            "styles": style_text,
            "resource": resource,
            "encoding": str(inspection.get("encoding") or "Unknown"),
            "embedded": embedded,
            "page": str(int(inspection.get("page") or 0) + 1),
        }
        for key, value in values.items():
            self._font_inspector_values[key].setText(value)
        color = values["color"]
        self._font_inspector_values["color"].setStyleSheet(
            f"background: {color}; border: 1px solid #666; "
            "border-radius: 8px; padding: 4px 8px;"
        )
        preview_family = {
            "Helv": "Arial",
            "Cour": "Courier New",
            "Times-Roman": "Times New Roman",
        }.get(values["suggested_font"], values["suggested_font"])
        sample_font = QFont(preview_family)
        sample_font.setPointSize(
            max(8, min(36, round(float(inspection.get("size") or 12.0))))
        )
        sample_font.setBold(bool(inspection.get("bold")))
        sample_font.setItalic(bool(inspection.get("italic")))
        self._font_sample.setFont(sample_font)
        self._font_sample.setText(values["text"][:160] or "Aa  Sample text")
        reusable = bool(inspection.get("usable_for_annotations"))
        self._font_apply_typewriter.setEnabled(reusable)
        self._font_apply_box.setEnabled(reusable)
        self._font_copy_name.setEnabled(True)
        self._font_inspector_status.setObjectName(
            "pageRangeStatus" if reusable else "fontInspectorWarning"
        )
        self._font_inspector_status.setText(
            "Font detected and available for new text annotations."
            if reusable
            else (
                "Font detected, but no compatible installed copy is available. "
                "Its name can still be copied."
            )
        )
        self._refresh_font_inspector_status_style()

    def _refresh_font_inspector_status_style(self) -> None:
        self._font_inspector_status.style().unpolish(self._font_inspector_status)
        self._font_inspector_status.style().polish(self._font_inspector_status)

    def _apply_inspected_font(self, tool: str) -> None:
        if self._font_inspection is not None:
            self.fontStyleApplyRequested.emit(tool, dict(self._font_inspection))

    def _copy_inspected_font_name(self) -> None:
        if self._font_inspection is not None:
            name = str(
                self._font_inspection.get("display_font")
                or self._font_inspection.get("raw_font")
                or ""
            )
            if name:
                self.fontNameCopyRequested.emit(name)

    def _set_annotation_color(self, value: str) -> None:
        self._current_color = value
        self._update_color_summary()
        self.annotationColorChanged.emit(value)
        self._emit_annotation_style()

    def _choose_color(self, initial: str) -> QColor | None:
        settings = QSettings()
        recent = settings.value("annotations/recent_colors", [], list) or []
        for index, value in enumerate(recent[:16]):
            QColorDialog.setCustomColor(index, QColor(str(value)))
        dialog = QColorDialog(QColor(initial), self)
        dialog.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, True)
        if dialog.exec() != QColorDialog.DialogCode.Accepted:
            return None
        color = dialog.selectedColor()
        values = [color.name(QColor.NameFormat.HexArgb)] + [
            str(value) for value in recent if str(value) != color.name(QColor.NameFormat.HexArgb)
        ]
        settings.setValue("annotations/recent_colors", values[:16])
        return color

    def _choose_custom_color(self) -> None:
        initial = SWATCHES.get(self._current_color, self._current_color)
        color = self._choose_color(initial)
        if color is None:
            return
        self._current_color = color.name()
        self._annot_opacity.setValue(round(color.alphaF() * 100))
        self.annotationColorChanged.emit(self._current_color)
        self._update_color_summary()
        self._emit_annotation_style()

    def _choose_fill_color(self) -> None:
        color = self._choose_color(self._current_fill or "#ffffff")
        if color is None:
            return
        self._current_fill = color.name()
        self._fill_color.setStyleSheet(f"background: {self._current_fill};")
        self._update_color_summary()
        self._emit_annotation_style()

    def _clear_fill_color(self) -> None:
        self._current_fill = ""
        self._fill_color.setStyleSheet("")
        self._update_color_summary()
        self._emit_annotation_style()

    @staticmethod
    def _relative_luminance(color: QColor) -> float:
        channels = []
        for value in (color.redF(), color.greenF(), color.blueF()):
            channels.append(
                value / 12.92
                if value <= 0.04045
                else ((value + 0.055) / 1.055) ** 2.4
            )
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    def _update_color_summary(self) -> None:
        stroke_name = SWATCHES.get(self._current_color, self._current_color)
        fill_name = SWATCHES.get(self._current_fill, self._current_fill)
        self._stroke_value.setText(f"Text/stroke: {stroke_name or 'none'}")
        self._fill_value.setText(f"Background: {fill_name or 'transparent'}")
        foreground = QColor(stroke_name)
        background = QColor(fill_name or "#ffffff")
        if not foreground.isValid() or not background.isValid():
            self._contrast_status.setText("Choose valid colors to preview contrast.")
            self._contrast_status.setObjectName("validationError")
        else:
            light = max(
                self._relative_luminance(foreground),
                self._relative_luminance(background),
            )
            dark = min(
                self._relative_luminance(foreground),
                self._relative_luminance(background),
            )
            ratio = (light + 0.05) / (dark + 0.05)
            if ratio < 3.0:
                self._contrast_status.setText(
                    f"Low contrast ({ratio:.1f}:1). Choose a darker text color or lighter Box color."
                )
                self._contrast_status.setObjectName("validationError")
            else:
                self._contrast_status.setText(f"Readable color contrast: {ratio:.1f}:1")
                self._contrast_status.setObjectName("pageRangeStatus")
        self._contrast_status.style().unpolish(self._contrast_status)
        self._contrast_status.style().polish(self._contrast_status)

    def _style_payload(self) -> dict[str, object]:
        return {
            "stroke": self._current_color,
            "fill": self._current_fill,
            "opacity": self._annot_opacity.value() / 100.0,
            "width": float(self._annot_width.value()),
            "font": self._annot_font.currentText(),
            "font_size": float(self._annot_font_size.value()),
            "alignment": int(self._annot_alignment.currentData() or 0),
        }

    def _emit_annotation_style(self, *_args) -> None:
        self.annotationStyleChanged.emit(self._style_payload())

    def set_annotation_defaults(self, values: dict[str, object]) -> None:
        controls = (
            self._annot_width,
            self._annot_opacity,
            self._annot_font,
            self._annot_font_size,
            self._annot_alignment,
        )
        blockers = [QSignalBlocker(control) for control in controls]
        try:
            self._current_color = str(
                values.get("stroke") or values.get("color") or "yellow"
            )
            self._current_fill = str(values.get("fill") or "")
            self._annot_width.setValue(float(values.get("width", 1.5)))
            self._annot_opacity.setValue(
                round(float(values.get("opacity", 1.0)) * 100)
            )
            self._annot_font.setCurrentText(str(values.get("font") or "Helv"))
            self._annot_font_size.setValue(
                round(float(values.get("font_size", 11.0)))
            )
            alignment = self._annot_alignment.findData(
                int(values.get("alignment", 0))
            )
            self._annot_alignment.setCurrentIndex(max(0, alignment))
            for key, button in self._color_buttons.items():
                button.setChecked(key == self._current_color)
            self._fill_color.setStyleSheet(
                f"background: {self._current_fill};" if self._current_fill else ""
            )
            self._update_color_summary()
        finally:
            del blockers


    def _browse_image(self) -> None:
        value, _ = QFileDialog.getOpenFileName(
            self, "Choose image", "", "Images (*.png *.jpg *.jpeg)"
        )
        if value:
            self.set_annotate_image(value)
            self.imagePathChanged.emit(value)

    def set_annotate_image(self, path: str) -> None:
        self._image_edit.setText(path)
        self._image_edit.setToolTip(path)

    def set_custom_stamps(
        self, stamps: dict[str, str], selected: str = ""
    ) -> None:
        """Replace the managed custom-stamp choices without emitting changes."""
        previous = selected or self.current_custom_stamp_name()
        self._stamp_kind.blockSignals(True)
        try:
            self._stamp_kind.clear()
            for name in STAMP_IDS:
                self._stamp_kind.addItem(name)
            selected_index = -1
            for name, path in sorted(stamps.items(), key=lambda item: item[0].casefold()):
                self._stamp_kind.addItem(
                    f"Custom: {name}", {"name": name, "path": path}
                )
                if name == previous:
                    selected_index = self._stamp_kind.count() - 1
            if selected_index >= 0:
                self._stamp_kind.setCurrentIndex(selected_index)
            else:
                self._stamp_kind.setCurrentText("Draft")
        finally:
            self._stamp_kind.blockSignals(False)
        self._stamp_remove.setEnabled(bool(self.current_custom_stamp_name()))

    def current_stamp(self) -> tuple[str, str]:
        """Return the built-in kind and optional custom image path."""
        data = self._stamp_kind.currentData()
        if isinstance(data, dict):
            return "Draft", str(data.get("path") or "")
        return self._stamp_kind.currentText() or "Draft", ""

    def current_custom_stamp_name(self) -> str:
        data = self._stamp_kind.currentData()
        return str(data.get("name") or "") if isinstance(data, dict) else ""

    def _stamp_selection_changed(self) -> None:
        kind, image_path = self.current_stamp()
        self._stamp_remove.setEnabled(bool(self.current_custom_stamp_name()))
        self.stampKindChanged.emit(kind)
        self.stampImageChanged.emit(image_path)

    def _remove_current_custom_stamp(self) -> None:
        name = self.current_custom_stamp_name()
        if name:
            self.customStampRemoveRequested.emit(name)


    def set_annotation_tool(self, tool: str) -> None:
        self._annot_tabs.setCurrentIndex(0)
        names = {
            "highlight": "Highlight", "underline": "Underline",
            "strikeout": "Strikeout", "squiggly": "Squiggly",
            "note": "Sticky Note", "ink": "Freehand Ink",
            "rect": "Rectangle", "line": "Line", "arrow": "Arrow",
            "ellipse": "Ellipse", "polygon": "Polygon",
            "freetext_typewriter": "Typewriter Text",
            "freetext_box": "Text Box", "freetext_callout": "Callout",
            "redact": "Redaction Mark", "stamp": "Stamp",
            "signature": "Signature Image", "image": "Insert Image",
        }
        hints = {
            "freetext_typewriter": (
                "Click to type. Use Alt + Arrow keys to move 1 px, or add Shift "
                "to move 5 px."
            ),
            "freetext_box": "Drag the exact Box area on the page. The placement guide remains visible even for pale or transparent styles.",
            "freetext_callout": "Drag the text Box; an arrow leader is created automatically.",
            "line": "Drag from the first endpoint to the second endpoint.",
            "arrow": "Drag from the tail to the arrow head.",
            "polygon": "Click vertices; double-click or right-click to finish.",
        }
        self._active_tool_title.setText(names.get(tool, tool.replace("_", " ").title()))
        self._active_tool_hint.setText(
            hints.get(tool, "Drag or click directly on the PDF page to create this annotation.")
        )
        style_tools = {
            "highlight", "underline", "strikeout", "squiggly", "ink", "rect",
            "line", "arrow", "ellipse", "polygon", "freetext_typewriter",
            "freetext_box", "freetext_callout",
        }
        color_visible = tool in style_tools
        width_visible = tool in {
            "ink", "rect", "line", "arrow", "ellipse", "polygon",
            "freetext_box", "freetext_callout",
        }
        text_visible = tool.startswith("freetext_")
        opacity_visible = tool in style_tools
        fill_visible = tool in {
            "rect", "ellipse", "polygon", "freetext_box", "freetext_callout"
        }
        stamp_visible = tool == "stamp"
        image_visible = tool in {"signature", "image"}
        self._annot_color_label.setText(
            "Text color" if text_visible else "Stroke / annotation color"
        )
        self._fill_color.setText("Box color…" if text_visible else "Fill…")
        self._annot_color_label.setVisible(color_visible)
        for button in self._color_buttons.values():
            button.setVisible(color_visible)
        self._custom_color.setVisible(color_visible)
        self._fill_color.setVisible(fill_visible)
        self._clear_fill.setVisible(fill_visible)
        self._annot_width_label.setVisible(width_visible)
        self._annot_width.setVisible(width_visible)
        self._set_form_field_visible(self._annot_opacity, opacity_visible)
        self._set_form_field_visible(self._annot_font, text_visible)
        self._set_form_field_visible(self._annot_font_size, text_visible)
        self._set_form_field_visible(self._annot_alignment, text_visible)
        self._stamp_label.setVisible(stamp_visible)
        self._stamp_kind.setVisible(stamp_visible)
        self._stamp_actions.setVisible(stamp_visible)
        self._image_label.setVisible(image_visible)
        self._image_edit.setVisible(image_visible)
        self._image_browse.setVisible(image_visible)

    def _set_form_field_visible(self, field: QWidget, visible: bool) -> None:
        field.setVisible(visible)
        label = self._style_form.labelForField(field)
        if label is not None:
            label.setVisible(visible)
    @staticmethod
    def _pdf_color_hex(value) -> str:
        if not value or len(value) < 3:
            return ""
        try:
            channels = [max(0, min(255, round(float(part) * 255))) for part in value[:3]]
        except (TypeError, ValueError):
            return ""
        return "#" + "".join(f"{part:02x}" for part in channels)

    def _load_selected_annotation(self, item, _previous=None) -> None:
        if item is None:
            self._property_text.clear()
            self._set_content_editor_visible(False)
            self._apply_properties.setEnabled(False)
            self._remove_selected.setEnabled(False)
            return
        entry = item.data(Qt.ItemDataRole.UserRole + 1) or {}
        editable_text = str(entry.get("kind") or "") in {"Text", "FreeText"}
        self._set_content_editor_visible(editable_text)
        self._property_text.setPlainText(str(entry.get("text") or ""))
        self._apply_properties.setText(
            "Apply Style & Content" if editable_text else "Apply Style"
        )
        self._apply_properties.setEnabled(True)
        self._remove_selected.setEnabled(True)
        stroke = self._pdf_color_hex(entry.get("stroke"))
        fill = self._pdf_color_hex(entry.get("fill"))
        if stroke:
            self._current_color = stroke
        self._current_fill = fill
        self._annot_opacity.setValue(
            round(float(entry.get("opacity", 1.0)) * 100)
        )
        self._annot_width.setValue(
            max(0.5, float(entry.get("width", 1.0) or 1.0))
        )
        font = str(entry.get("font") or "")
        if font:
            self._annot_font.setCurrentText(font)
        font_size = float(entry.get("font_size", 0.0) or 0.0)
        if font_size > 0:
            self._annot_font_size.setValue(round(font_size))
        alignment_index = self._annot_alignment.findData(
            int(entry.get("alignment", 0) or 0)
        )
        if alignment_index >= 0:
            self._annot_alignment.setCurrentIndex(alignment_index)
        self._fill_color.setStyleSheet(
            f"background: {fill};" if fill else ""
        )
        self._update_color_summary()
        self._emit_annotation_selected(item)

    def _set_content_editor_visible(self, visible: bool) -> None:
        self._property_text.setVisible(visible)
        label = self._properties_form.labelForField(self._property_text)
        if label is not None:
            label.setVisible(visible)

    def _emit_annotation_selected(self, item) -> None:
        if item is None:
            return
        entry = item.data(Qt.ItemDataRole.UserRole + 1) or {}
        page = entry.get("page")
        xref = entry.get("xref")
        if page is not None and xref is not None:
            self.annotationSelected.emit(int(page), int(xref))

    def _apply_selected_annotation(self) -> None:
        item = self._annot_list.currentItem()
        if item is None:
            return
        xref = item.data(Qt.ItemDataRole.UserRole)
        if xref is None:
            return
        payload = self._style_payload()
        entry = item.data(Qt.ItemDataRole.UserRole + 1) or {}
        if str(entry.get("kind") or "") in {"Text", "FreeText"}:
            payload["text"] = self._property_text.toPlainText()
        page = int(entry.get("page", 0))
        self.editAnnotationRequested.emit(page, int(xref), payload)


    def refresh_annotation_list(self, entries: list[dict] | None) -> None:
        selected = self._annot_list.currentItem()
        selected_key = None
        if selected is not None:
            selected_entry = selected.data(Qt.ItemDataRole.UserRole + 1) or {}
            selected_key = (selected_entry.get("page"), selected_entry.get("xref"))
        # Rebuilding the model is an internal synchronization operation.  In
        # particular, restoring the current item must not emit
        # ``annotationSelected`` and navigate back to the annotation's page.
        # That previously made Next Page appear broken after moving an item.
        with QSignalBlocker(self._annot_list):
            self._annot_list.clear()
            kinds = sorted(
                {str(entry.get("kind") or "Unknown") for entry in entries or []}
            )
            previous_kind = str(self._annot_type_filter.currentData() or "")
            with QSignalBlocker(self._annot_type_filter):
                self._annot_type_filter.clear()
                self._annot_type_filter.addItem("All types", "")
                for kind in kinds:
                    self._annot_type_filter.addItem(kind, kind)
                index = self._annot_type_filter.findData(previous_kind)
                self._annot_type_filter.setCurrentIndex(max(0, index))
            restore_item = None
            for entry in entries or []:
                xref = entry.get("xref")
                if xref is None:
                    continue
                page = int(entry.get("page", 0))
                kind = str(entry.get("kind") or "Unknown")
                text = str(entry.get("text") or "").replace("\n", " ").strip()
                author = str(entry.get("title") or "").strip()
                summary = text[:48] + ("…" if len(text) > 48 else "")
                details = " · ".join(part for part in (summary, author) if part)
                label = f"{kind} · Page {page + 1}"
                if details:
                    label += f" · {details}"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole + 1, entry)
                item.setData(Qt.ItemDataRole.UserRole, int(xref))
                self._annot_list.addItem(item)
                if selected_key == (page, int(xref)):
                    restore_item = item
            self._filter_annotations()
            if restore_item is not None:
                self._annot_list.setCurrentItem(restore_item)

    def _filter_annotations(self, *_args) -> None:
        query = self._annot_search.text().strip().casefold()
        kind_filter = str(self._annot_type_filter.currentData() or "")
        for index in range(self._annot_list.count()):
            item = self._annot_list.item(index)
            entry = item.data(Qt.ItemDataRole.UserRole + 1) or {}
            haystack = " ".join(
                str(entry.get(key) or "")
                for key in ("kind", "text", "title", "subject", "creation_date")
            ).casefold()
            matches = (not query or query in haystack) and (
                not kind_filter or str(entry.get("kind") or "") == kind_filter
            )
            item.setHidden(not matches)

    def select_annotation(self, page: int, xref: int) -> None:
        self._annot_tabs.setCurrentIndex(1)
        for index in range(self._annot_list.count()):
            item = self._annot_list.item(index)
            entry = item.data(Qt.ItemDataRole.UserRole + 1) or {}
            if int(entry.get("page", -1)) == int(page) and int(
                entry.get("xref", -1)
            ) == int(xref):
                self._annot_list.setCurrentItem(item)
                self._annot_list.scrollToItem(item)
                return

    def _remove_selected_annotation(self) -> None:
        item = self._annot_list.currentItem()
        if item is not None:
            index = item.data(Qt.ItemDataRole.UserRole)
            if index is not None:
                entry = item.data(Qt.ItemDataRole.UserRole + 1) or {}
                self.removeAnnotationRequested.emit(
                    int(entry.get("page", 0)), int(index)
                )

    def _add_validation_label(self, layout: QVBoxLayout) -> QLabel:
        label = QLabel()
        label.setObjectName("validationError")
        label.setWordWrap(True)
        label.hide()
        layout.addWidget(label)
        return label

    def _add_quick_buttons(self, layout: QVBoxLayout, pages: QLineEdit) -> None:
        row = QHBoxLayout()
        row.setSpacing(S.XS)
        for text, value in (("All", "all"), ("Odd", "odd"), ("Even", "even"), ("Current", "current")):
            button = QPushButton(text)
            button.setProperty("secondary", True)
            button.setProperty("compact", True)
            button.setFixedHeight(26)
            button.setToolTip(f"Select {value} pages")
            button.clicked.connect(lambda _checked=False, v=value: pages.setText(v))
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)

    def _validate_pages_input(self, edit: QLineEdit, text: str, *, allow_empty: bool = True) -> None:
        """Validate page range text and show status via the input's style and a sibling label."""
        stripped = text.strip()
        if not stripped:
            edit.setProperty("invalid", False)
            edit.style().unpolish(edit)
            edit.style().polish(edit)
            label = self._find_validation_label(edit)
            if label:
                label.hide()
            return
        if self._page_count <= 0:
            return
        normalized = stripped.casefold()
        try:
            if normalized in {"all", "current"}:
                pages = list(range(self._page_count)) if normalized == "all" else [0]
            elif normalized in {"odd", "even"}:
                start = 1 if normalized == "odd" else 2
                pages = list(range(start - 1, self._page_count, 2))
            else:
                pages = parse_page_range(stripped, self._page_count)
            edit.setProperty("invalid", False)
            label = self._find_validation_label(edit)
            if label:
                label.setText(f"{len(pages)} page{'s' if len(pages) != 1 else ''} selected")
                label.setObjectName("pageRangeStatus")
                label.style().unpolish(label)
                label.style().polish(label)
                label.show()
        except Exception as exc:
            edit.setProperty("invalid", True)
            label = self._find_validation_label(edit)
            if label:
                label.setText(str(exc))
                label.setObjectName("validationError")
                label.style().unpolish(label)
                label.style().polish(label)
                label.show()
        edit.style().unpolish(edit)
        edit.style().polish(edit)

    def _find_validation_label(self, edit: QLineEdit) -> QLabel | None:
        page = edit.parentWidget()
        while page is not None and page not in self._pages.values():
            page = page.parentWidget()
        if page is None:
            return None
        return getattr(page, "validation_label", None) or getattr(self, "_validation_rotate", None)

    def show_tool(self, key: str, title: str) -> bool:
        page = self._pages.get(key)
        if not page:
            return False
        was_visible = self.isVisible() and self._panel_width > 0
        self._title.setText(title)
        self._stack.setCurrentWidget(page)
        self._width_animation.stop()
        self._closing = False
        self.show()
        if not was_visible and self._animations_enabled:
            self.panelWidth = 0
            self._width_animation.setStartValue(0)
            self._width_animation.setEndValue(D.CONTEXT_W)
            self._width_animation.start()
        else:
            self.panelWidth = D.CONTEXT_W
        return True

    def close_animated(self) -> None:
        self._width_animation.stop()
        self._closing = True
        if not self.isVisible() or not self._animations_enabled:
            self.panelWidth = 0
            self.hide()
            return
        self._width_animation.setStartValue(self._panel_width)
        self._width_animation.setEndValue(0)
        self._width_animation.start()

    def _animation_finished(self) -> None:
        if self._closing:
            self.panelWidth = 0
            self.hide()
            self._closing = False
        else:
            self.panelWidth = D.CONTEXT_W

    def set_animations_enabled(self, enabled: bool) -> None:
        self._animations_enabled = enabled
        self._close.set_animations_enabled(enabled)

    def set_page_count(self, count: int) -> None:
        self._page_count = count
        insert = self._pages.get("insert")
        if insert:
            insert.position_spin.setMaximum(max(1, count + 1))  # type: ignore[attr-defined]

    def set_insert_source(self, path: str) -> None:
        insert = self._pages.get("insert")
        if insert:
            insert.source_edit.setText(path)  # type: ignore[attr-defined]

    def refresh_icons(self) -> None:
        self._close.refresh_icon()
