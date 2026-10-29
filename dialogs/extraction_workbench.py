"""Quick workbench layout and visual preferences, with no extraction data storage."""
from __future__ import annotations

from PyQt6.QtCore import QRect, QSettings, Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ui import responsive

LAYOUT_GROUP = "dialogs/extract-region-workbench-v3"
LEGACY_LAYOUT_GROUP = "dialogs/extract-region-workbench-v2"


class ExtractionWorkbench:
    def setup_workbench(self):
        self._layout_ready = False
        self._restored_layout = False
        self._results_focused = False
        self._results_collapsed = False
        self._normal_wide_state = None
        self._normal_right_state = None
        self._geometry_restored = False
        self._workbench_screen = None
        self._watching_window = False
        self._settings = QSettings()
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.layout().removeWidget(self.buttons)
        self.buttons.hide()
        old_splitter = self.editor_splitter
        self.layout().removeWidget(old_splitter)

        self.fields_panel = QWidget()
        fields = QVBoxLayout(self.fields_panel)
        fields.setContentsMargins(0, 0, 0, 0)
        fields.addWidget(QLabel("Extraction fields"))
        self.list.setMinimumHeight(40)
        self.list.setMaximumHeight(16777215)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        fields.addWidget(self.list, 1)
        self.add_button, self.duplicate_button, self.delete_button = self.region_buttons
        self.add_button.setText("New region")
        fields.addWidget(self.add_button)
        tools = QHBoxLayout()
        tools.addWidget(self.duplicate_button)
        tools.addWidget(self.delete_button)
        fields.addLayout(tools)
        self.hint.hide()
        self.add_button.setToolTip("Drag on the PDF after New region. Esc cancels. Space pans; Ctrl+wheel zooms.")
        self.fields_panel.setMinimumWidth(140)

        self.inspector_layout.removeItem(self.region_tools)
        self.region_tools.setParent(None)
        self.region_tools.deleteLater()
        self.sample.hide()
        self.inspector_layout.removeWidget(self.sample)
        self.inspector.setMinimumWidth(250)
        for control in (self.scope, self.role, self.policy):
            self.controls_form.setRowVisible(control, False)
        self.advanced = QPushButton("Position / size / advanced rules")
        self.advanced.setCheckable(True)
        self.inspector_layout.insertWidget(1, self.advanced)
        self.advanced.toggled.connect(self.toggle_advanced)
        self.toggle_advanced(False)

        self.preview_details = QPlainTextEdit()
        self.preview_details.setReadOnly(True)
        self.preview_details.setPlaceholderText("Select a field to inspect Raw / Clean text and issues.")
        self.tabs = QTabWidget()
        self.tabs.addTab(self.inspector, "Properties")
        self.tabs.addTab(self.preview_details, "Text preview")
        self.tabs.setMinimumWidth(260)

        self.editor_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.editor_splitter.setChildrenCollapsible(False)
        self.editor_splitter.addWidget(self.fields_panel)
        self.editor_splitter.addWidget(self.tabs)
        self.editor_splitter.setStretchFactor(1, 1)
        self.editor_page = QWidget()
        layout = QVBoxLayout(self.editor_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.editor_splitter)
        self.editor_page.setMinimumHeight(160)
        old_splitter.hide()
        old_splitter.deleteLater()

        self.show_all = QCheckBox("All regions")
        self.show_all.setChecked(True)
        self.show_all.setToolTip("Clear to show only the selected region")
        self.show_all.toggled.connect(self.set_all_regions)
        self.properties_toggle = QPushButton("Properties")
        self.properties_toggle.setCheckable(True)
        self.properties_toggle.setChecked(True)
        self.properties_toggle.toggled.connect(self.tabs.setVisible)
        self.fields_toggle = QPushButton("Fields")
        self.fields_toggle.setCheckable(True)
        self.fields_toggle.setChecked(True)
        self.fields_toggle.toggled.connect(self.fields_panel.setVisible)
        self.top_layout.addWidget(self.show_all)
        self.top_layout.addWidget(self.fields_toggle)
        self.top_layout.addWidget(self.properties_toggle)
        self.page.setMaximumWidth(125)
        self._layout_ready = True

    def finish_workbench(self):
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.right_splitter.setChildrenCollapsible(False)
        self.right_splitter.addWidget(self.editor_page)
        self.right_splitter.addWidget(self.results_page)
        self.right_page = QWidget()
        right = QVBoxLayout(self.right_page)
        right.setContentsMargins(0, 0, 0, 0)
        right.addWidget(self.right_splitter, 1)
        right.addWidget(self.status)
        right.addWidget(self.progress)
        right.addWidget(self.action_bar)
        self.wide = QSplitter(Qt.Orientation.Horizontal)
        self.wide.setChildrenCollapsible(False)
        self.wide.addWidget(self.view)
        self.wide.addWidget(self.right_page)
        self.wide.setStretchFactor(0, 1)
        self.wide.setStretchFactor(1, 1)
        self.view.setMinimumWidth(220)
        self.layout().insertWidget(1, self.wide, 1)
        self._layout_ready = True
        geometry_group = LAYOUT_GROUP if self._settings.contains(LAYOUT_GROUP+"/geometry") else LEGACY_LAYOUT_GROUP
        geometry = self._settings.value(geometry_group+"/geometry")
        if geometry:
            self._geometry_restored = self.restoreGeometry(geometry)
            normal = self._settings.value(geometry_group+"/normal_rect")
            if isinstance(normal, QRect) and normal.isValid():
                # Qt may clamp restoreGeometry to the old/primary screen before
                # our current-screen bounds helper runs (notably after docking).
                self.setGeometry(normal)
        if not self._geometry_restored:
            area = responsive.available_area(self)
            self.resize(round(area.width()*.92), round(area.height()*.92))
        responsive.fit_window(self)

    def showEvent(self, event):
        super().showEvent(event)
        handle = self.windowHandle()
        if handle is not None and not self._watching_window:
            self._watching_window = True
            handle.screenChanged.connect(self.watch_workbench_screen)
            self.watch_workbench_screen(handle.screen())
        if hasattr(self, "wide") and not self._restored_layout:
            self._restored_layout = True
            QTimer.singleShot(0, self.restore_workbench)

    def watch_workbench_screen(self, screen):
        if self._workbench_screen is not None:
            for signal in (self._workbench_screen.availableGeometryChanged,
                           self._workbench_screen.logicalDotsPerInchChanged):
                try:
                    signal.disconnect(self.queue_screen_fit)
                except (RuntimeError, TypeError):
                    pass  # The previous monitor may already have been removed.
        self._workbench_screen = screen
        if screen is not None:
            screen.availableGeometryChanged.connect(self.queue_screen_fit)
            screen.logicalDotsPerInchChanged.connect(self.queue_screen_fit)
        self.queue_screen_fit()

    def queue_screen_fit(self, *_):
        QTimer.singleShot(0, self.fit_workbench_screen)

    def fit_workbench_screen(self):
        if not self.closed and not self.isMaximized():
            responsive.fit_window(self)

    def restore_workbench(self):
        if self.closed:
            return
        self.arrange()
        controls = self._settings.value(LAYOUT_GROUP+"/controls")
        if controls:
            self.editor_splitter.restoreState(controls)
        else:
            self.editor_splitter.setSizes([170, 280])
        horizontal = self._settings.value(LAYOUT_GROUP+"/horizontal")
        if horizontal:
            self.wide.restoreState(horizontal)
        else:
            width = self.wide.width()
            self.wide.setSizes([round(width*.48), round(width*.52)])
        vertical = self._settings.value(LAYOUT_GROUP+"/vertical")
        if vertical:
            self.right_splitter.restoreState(vertical)
        else:
            height = self.right_splitter.height()
            bottom = max(self.results_page.minimumHeight(), round(height*.66))
            self.right_splitter.setSizes([max(160, height-bottom), bottom])
        self.properties_toggle.setChecked(self._settings.value(LAYOUT_GROUP+"/properties", True, type=bool))
        self.fields_toggle.setChecked(self._settings.value(LAYOUT_GROUP+"/list", True, type=bool))
        if self._settings.value(LAYOUT_GROUP+"/collapsed", False, type=bool):
            self.collapse_results()

    def save_workbench(self):
        if not hasattr(self, "wide"):
            return
        self._settings.setValue(LAYOUT_GROUP+"/geometry", self.saveGeometry())
        self._settings.setValue(LAYOUT_GROUP+"/normal_rect", self.normalGeometry() if self.isMaximized() else QWidget.geometry(self))
        self._settings.setValue(LAYOUT_GROUP+"/controls", self.editor_splitter.saveState())
        self._settings.setValue(LAYOUT_GROUP+"/horizontal", self._normal_wide_state or self.wide.saveState())
        self._settings.setValue(LAYOUT_GROUP+"/vertical", self._normal_right_state or self.right_splitter.saveState())
        self._settings.setValue(LAYOUT_GROUP+"/properties", self.properties_toggle.isChecked())
        self._settings.setValue(LAYOUT_GROUP+"/list", self.fields_toggle.isChecked())
        self._settings.setValue(LAYOUT_GROUP+"/collapsed", self._results_collapsed)

    def arrange(self):
        if not hasattr(self, "wide"):
            return
        if self._results_collapsed:
            self.results_page.setMinimumHeight(self.results_header.sizeHint().height()+self.selection_row.sizeHint().height()+16)
        else:
            rows = 8 if self.width() >= 1280 else 6
            minimum = (rows*self.table.verticalHeader().defaultSectionSize()+self.table.horizontalHeader().height()
                       + self.table.horizontalScrollBar().sizeHint().height()+2*self.table.frameWidth()
                       + self.results_header.sizeHint().height()+self.navigation.sizeHint().height()
                       + self.selection_row.sizeHint().height()+32)
            self.results_page.setMinimumHeight(minimum)

    def toggle_advanced(self, checked):
        for control in (*self.region, self.label, self.minimum, self.maximum, self.trim):
            self.controls_form.setRowVisible(control, checked)
        self.size_button.setVisible(checked)

    def set_all_regions(self, checked):
        self.show_all_regions = checked
        self.view.render_regions()

    def focus_results(self):
        if self._results_collapsed:
            self.collapse_results()
        if not self._results_focused:
            self._normal_wide_state = self.wide.saveState()
            self._normal_right_state = self.right_splitter.saveState()
            self.view.hide()
            self.editor_page.hide()
        else:
            self.view.show()
            self.editor_page.show()
            if self._normal_wide_state:
                self.wide.restoreState(self._normal_wide_state)
            if self._normal_right_state:
                self.right_splitter.restoreState(self._normal_right_state)
            self._normal_wide_state = None
            self._normal_right_state = None
        self._results_focused = not self._results_focused
        self.result_focus_button.setText("Restore" if self._results_focused else "Expand")

    def collapse_results(self):
        if self._results_focused:
            self.focus_results()
        self._results_collapsed = not self._results_collapsed
        if self._results_collapsed:
            self._normal_right_state = self.right_splitter.saveState()
        self.table.setVisible(not self._results_collapsed)
        self.navigation.setVisible(not self._results_collapsed)
        self.result_focus_button.setEnabled(not self._results_collapsed)
        self.collapse_button.setText("Show table" if self._results_collapsed else "Hide table")
        self.arrange()
        if self._results_collapsed:
            self.right_splitter.setSizes([self.right_splitter.height(), self.results_page.minimumHeight()])
        elif self._normal_right_state:
            self.right_splitter.restoreState(self._normal_right_state)
            self._normal_right_state = None
