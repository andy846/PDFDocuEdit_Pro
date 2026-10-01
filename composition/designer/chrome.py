"""Menus, toolbars, layers and layout commands for Document Designer."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QInputDialog,
    QLabel,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolBar,
    QToolButton,
)

from ui.icons import icon


class DesignerChrome:
    def _build_actions(self):
        self.actions = {}
        menus = {name: self.menuBar().addMenu(name) for name in
                 ("&File", "&Edit", "&Insert", "&Page", "&Arrange", "&View", "&Data", "&Production", "&Help")}
        self.project_toolbar = QToolBar("Project", self)
        self.project_toolbar.setMovable(False)
        self.project_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(self.project_toolbar)
        self.insert_toolbar = QToolBar("Insert & view", self)
        self.insert_toolbar.setMovable(False)
        self.insert_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBarBreak()
        self.addToolBar(self.insert_toolbar)

        def action(key, text, slot, menu, shortcut=None, symbol=None, toolbar=None):
            value = QAction(icon(symbol or "file-text"), text, self)
            value.setProperty("designer_icon", symbol or "file-text")
            value.triggered.connect(slot)
            if shortcut:
                value.setShortcut(shortcut)
            value.setStatusTip(text.replace("&", ""))
            self.actions[key] = value
            menus[menu].addAction(value)
            if toolbar:
                toolbar.addAction(value)
            return value
        action("new", "New project", self.new_project, "&File", QKeySequence.StandardKey.New,
               "file-text", self.project_toolbar)
        action("open", "Open project…", self.open_project, "&File", QKeySequence.StandardKey.Open,
               "folder-open", self.project_toolbar)
        action("save", "Save", self.save_project, "&File", QKeySequence.StandardKey.Save,
               "save", self.project_toolbar)
        action("save_as", "Save as…", lambda: self.save_project(save_as=True), "&File",
               "Ctrl+Shift+S", "save-as")
        self.recent_menu = menus["&File"].addMenu("Recent projects")
        menus["&File"].addSeparator()
        action("background", "Use PDF background…", self.add_background, "&File", symbol="image")
        action("remove_background", "Remove PDF background", self.remove_background, "&File")
        action("rename", "Rename project…", self.rename_template, "&File")
        menus["&File"].addSeparator()
        action("close", "Close designer", self.close, "&File", "Ctrl+W", "x")
        self.project_toolbar.addSeparator()
        for key, value in (("undo", self.undo.createUndoAction(self, "Undo")),
                           ("redo", self.undo.createRedoAction(self, "Redo"))):
            value.setIcon(icon(key))
            value.setProperty("designer_icon", key)
            value.setShortcut(QKeySequence.StandardKey.Undo if key == "undo" else QKeySequence.StandardKey.Redo)
            menus["&Edit"].addAction(value)
            self.project_toolbar.addAction(value)
            self.actions[key] = value
        menus["&Edit"].addSeparator()
        for key, text, shortcut, symbol in [
            ("cut", "Cut", "Ctrl+X", "scissors"), ("copy", "Copy", "Ctrl+C", "files"),
            ("paste", "Paste", "Ctrl+V", "files"), ("duplicate", "Duplicate", "Ctrl+D", "files"),
            ("delete", "Delete", "Delete", "trash"),
        ]:
            action(key, text, lambda checked=False, name=key: self.object_command(name),
                   "&Edit", shortcut, symbol)
        action("select_all", "Select all objects", self.select_all_objects, "&Edit", "Ctrl+A", "layers")
        for text, kind, symbol in [("Text", "text", "text-cursor-input"), ("Image", "image", "image"),
                                   ("Line", "line", "line-tool"), ("Box", "rectangle", "square"),
                                   ("Code 128", "code128", "scan"), ("QR code", "qr", "scan")]:
            action("insert_"+kind, text, lambda checked=False, value=kind: self.add_element(value),
                   "&Insert", symbol=symbol, toolbar=self.insert_toolbar if kind not in {"code128", "qr"} else None)
        barcode = self.barcode_button = QToolButton()
        barcode.setText("Barcode")
        barcode.setIcon(icon("scan"))
        barcode.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        barcode_menu = QMenu(barcode)
        barcode_menu.addAction(self.actions["insert_code128"])
        barcode_menu.addAction(self.actions["insert_qr"])
        barcode.setMenu(barcode_menu)
        barcode.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.insert_toolbar.addWidget(barcode)
        action("variable", "Variable field…", self.insert_variable_field, "&Insert", symbol="table",
               toolbar=self.insert_toolbar)
        for name, label in [("left", "Align left"), ("center", "Align horizontal centres"), ("right", "Align right"),
                            ("top", "Align top"), ("middle", "Align vertical centres"), ("bottom", "Align bottom"),
                            ("horizontal", "Distribute horizontally"), ("vertical", "Distribute vertically"),
                            ("front", "Bring to front"), ("back", "Send to back")]:
            action("arrange_"+name, label, lambda checked=False, mode=name: self.arrange_objects(mode),
                   "&Arrange", symbol="layers")
        action("repair_glyph", "Repair missing glyph…", self.edit_glyph_repairs, "&Arrange", symbol="font-inspect")
        action("cjk", "Use CJK font for selected text", self.use_cjk_font, "&Arrange", symbol="font-inspect")
        for key, label, slot in (
            ("page_add", "Add blank template page", self.add_template_page),
            ("page_duplicate", "Duplicate template page", lambda: self.add_template_page(duplicate=True)),
            ("page_delete", "Delete template page", self.delete_template_page),
            ("page_up", "Move template page earlier", lambda: self.move_template_page(-1)),
            ("page_down", "Move template page later", lambda: self.move_template_page(1)),
            ("page_rename", "Rename template page…", self.rename_template_page),
        ):
            action(key, label, slot, "&Page", symbol="file-text")
        action("page_previous", "Previous template page", lambda: self.select_template_page(self.page_index-1),
               "&Page", "Alt+PgUp")
        action("page_next", "Next template page", lambda: self.select_template_page(self.page_index+1),
               "&Page", "Alt+PgDown")
        action("page_size", "Current page size…", self.page_size, "&Page", symbol="square")
        action("fit_page", "Fit page", lambda: self.canvas.fit_page(), "&View", "Ctrl+0", "monitor")
        action("zoom_in", "Zoom in", lambda: self.canvas.zoom_by(1.2), "&View", "Ctrl++", "plus")
        action("zoom_out", "Zoom out", lambda: self.canvas.zoom_by(1/1.2), "&View", "Ctrl+-", "minus")
        for key, label, slot in [("grid", "Show 5 mm grid", lambda on: self.canvas.set_grid(on)),
                                 ("snap", "Snap to 5 mm grid", lambda on: self.canvas.set_snap(on)),
                                 ("data_panel", "Data / Layers panel", lambda on: self.left_panel.setVisible(on)),
                                 ("properties", "Properties panel", lambda on: self.properties_scroll.setVisible(on))]:
            value = action(key, label, slot, "&View", symbol="settings")
            value.setCheckable(True)
            value.setChecked(key in {"data_panel", "properties"})
        self.project_toolbar.addSeparator()
        action("import", "Import data…", self.import_data, "&Data", "Ctrl+I", "table", self.project_toolbar)
        action("preview", "Preview records", lambda: self.tabs.setCurrentIndex(2), "&Data", "F5", "search")
        action("generate", "Generate PDF…", self.generate_pdf, "&Production", "Ctrl+Shift+G",
               "printer", self.project_toolbar)
        action("cancel", "Cancel job", self.cancel_job, "&Production", symbol="x")
        action("help", "Designer shortcuts", self.show_shortcuts, "&Help", "F1", "keyboard")
        self._refresh_recent()

    def _finish_designer_ui(self):
        for key in ("undo", "redo"):
            button = self.project_toolbar.widgetForAction(self.actions[key])
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.record.setPrefix("Record ")
        self.record.setMinimumWidth(105)
        self.insert_toolbar.addSeparator()
        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.zoom_combo.addItems(["Fit page", "25%", "50%", "75%", "100%", "125%", "150%", "200%", "300%"])
        self.zoom_combo.setMaximumWidth(105)
        self.zoom_combo.setAccessibleName("Canvas zoom")
        self.zoom_combo.activated.connect(self._zoom_selected)
        self.zoom_combo.lineEdit().editingFinished.connect(self._zoom_selected)
        self.font_size_tool = QDoubleSpinBox()
        self.font_size_tool.setRange(1, 500)
        self.font_size_tool.setDecimals(1)
        self.font_size_tool.setSuffix(" pt")
        self.font_size_tool.setMaximumWidth(100)
        self.font_size_tool.setToolTip("Font size of the selected text object")
        self.font_size_tool.setAccessibleName("Selected text font size")
        self.font_size_tool.editingFinished.connect(self._toolbar_font_size)
        self.insert_toolbar.addWidget(self.font_size_tool)
        self.insert_toolbar.addWidget(self.zoom_combo)
        self.insert_toolbar.addAction(self.actions["fit_page"])
        self.canvas.zoomChanged.connect(self._zoom_changed)
        self.canvas.pointerMoved.connect(
            lambda x, y: self.statusBar().showMessage(f"X {x:.2f} mm · Y {y:.2f} mm", 2000))
        self.selection_status = QLabel("No selection")
        self.statusBar().addPermanentWidget(self.selection_status)
        self.page_status = QLabel("A4 · 210 × 297 mm")
        self.statusBar().addPermanentWidget(self.page_status)
        self.review_error_button = QPushButton("Review failed object / record")
        self.review_error_button.hide()
        self.repair_error_button = QPushButton("Repair missing glyph — keep primary font")
        self.repair_error_button.hide()
        self.repair_error_button.clicked.connect(self.repair_failed_glyph)
        self.review_error_button.clicked.connect(self.review_failed_object)
        self.report_button = QPushButton("Open reports folder")
        self.report_button.setEnabled(False)
        self.report_button.clicked.connect(self.open_report_folder)
        production_layout = self.production_page.layout()
        production_layout.addWidget(self.review_error_button)
        production_layout.addWidget(self.repair_error_button)
        production_layout.addWidget(self.report_button)
        self.last_report_dir = ""
        self.failed_record = None
        self.failed_object = ""
        self.failed_codepoint = ""
        geometry = self.preferences.value("geometry")
        splitter = self.preferences.value("splitter")
        if geometry:
            self.restoreGeometry(geometry)
        if splitter:
            self.splitter.restoreState(splitter)

    def _update_actions(self):
        if not hasattr(self, "actions"):
            return
        selected = self.canvas.selected_ids()
        element = self.properties.element
        text_selected = bool(element and (element.type == "text" or element.show_barcode_text))
        self.font_size_tool.setEnabled(text_selected)
        if text_selected:
            self.font_size_tool.blockSignals(True)
            self.font_size_tool.setValue(element.font.size_pt)
            self.font_size_tool.blockSignals(False)
        busy = bool(self.import_worker or self.production_worker)
        for key in ("cut", "copy", "duplicate", "delete", "cjk", "repair_glyph"):
            self.actions[key].setEnabled(bool(selected) and not busy and not self.canvas.mode_preview)
        self.actions["paste"].setEnabled(bool(self.clipboard) and not busy)
        for key in ("new", "open", "save", "save_as", "background", "remove_background",
                    "rename", "import", "page_size", "select_all"):
            self.actions[key].setEnabled(not busy)
        for key, value in self.actions.items():
            if key.startswith("arrange_"):
                value.setEnabled(bool(selected) and not busy)
            elif key.startswith("insert_") or key == "variable":
                value.setEnabled(not busy)
        self.actions["generate"].setEnabled(bool(self._store()) and not busy and not self.font_requests)
        self.actions["cancel"].setEnabled(busy)
        self.selection_status.setText(f"{len(selected)} selected" if selected else "No selection")
        self._update_page_actions()
        self.actions["page_previous"].setEnabled(self.page_index > 0)
        self.actions["page_next"].setEnabled(self.page_index < len(self.template.pages)-1)
        self.page_status.setText(f"Page {self.page_index+1}/{len(self.template.pages)} · {self.page.width_mm:.2f} × {self.page.height_mm:.2f} mm")

    def _refresh_layers(self):
        self._layers_updating = True
        self.layers.clear()
        for element in reversed(self.page.elements):
            value = element.value.replace("\n", " ")[:45] if element.value else element.type.title()
            item = QListWidgetItem(f"{element.type.title()} · {value}")
            item.setData(Qt.ItemDataRole.UserRole, element.id)
            item.setToolTip(value + "\n" + element.id)
            self.layers.addItem(item)
        self._layers_updating = False
        self._sync_layers()

    def _sync_layers(self):
        if not hasattr(self, "layers") or self._layers_updating:
            return
        selected = set(self.canvas.selected_ids())
        self._layers_updating = True
        for index in range(self.layers.count()):
            item = self.layers.item(index)
            item.setSelected(item.data(Qt.ItemDataRole.UserRole) in selected)
        self._layers_updating = False

    def _layers_selected(self):
        if not self._layers_updating:
            self.canvas.select_ids([item.data(Qt.ItemDataRole.UserRole) for item in self.layers.selectedItems()])

    def select_all_objects(self):
        if self.tabs.currentIndex() != 1:
            self.tabs.setCurrentIndex(1)
        self.canvas.select_ids([element.id for element in self.page.elements])

    def arrange_objects(self, mode):
        selected = set(self.canvas.selected_ids())
        before, after = self.template.to_dict(), self.template.to_dict()
        values = [element for element in self._page_dict(after)["elements"] if element["id"] in selected]
        if not values:
            return
        if mode in {"front", "back"}:
            others = [element for element in self._page_dict(after)["elements"] if element["id"] not in selected]
            self._page_dict(after)["elements"] = others + values if mode == "front" else values + others
        else:
            x0, y0 = min(e["x_mm"] for e in values), min(e["y_mm"] for e in values)
            x1 = max(e["x_mm"] + e["width_mm"] for e in values)
            y1 = max(e["y_mm"] + e["height_mm"] for e in values)
            if mode in {"horizontal", "vertical"}:
                if len(values) < 3:
                    self._error("Select at least three objects to distribute.")
                    return
                axis, size, low, high = ("x_mm", "width_mm", x0, x1) if mode == "horizontal" else ("y_mm", "height_mm", y0, y1)
                values.sort(key=lambda e: e[axis])
                gap = (high-low-sum(e[size] for e in values))/(len(values)-1)
                position = low
                for element in values:
                    element[axis] = round(position, 2)
                    position += element[size]+gap
            else:
                for element in values:
                    if mode == "left":
                        element["x_mm"] = x0
                    elif mode == "center":
                        element["x_mm"] = (x0+x1-element["width_mm"])/2
                    elif mode == "right":
                        element["x_mm"] = x1-element["width_mm"]
                    elif mode == "top":
                        element["y_mm"] = y0
                    elif mode == "middle":
                        element["y_mm"] = (y0+y1-element["height_mm"])/2
                    elif mode == "bottom":
                        element["y_mm"] = y1-element["height_mm"]
        self._commit(before, after, "Arrange " + mode, list(selected))

    def _zoom_selected(self, *args):
        text = self.zoom_combo.currentText().strip()
        if text == "Fit page":
            self.canvas.fit_page()
            return
        try:
            self.canvas.set_zoom(float(text.rstrip("%"))/100)
        except ValueError:
            self._error("Enter a zoom percentage between 10% and 800%.")

    def _zoom_changed(self, value):
        self.zoom_combo.blockSignals(True)
        self.zoom_combo.setCurrentText(f"{value*100:.0f}%")
        self.zoom_combo.blockSignals(False)

    def _update_navigation(self, *args):
        current, count = self.record.value(), self.record_count
        self.first.setEnabled(count > 0 and current > 1)
        self.previous.setEnabled(count > 0 and current > 1)
        self.next.setEnabled(count > 0 and current < count)
        self.last.setEnabled(count > 0 and current < count)

    def insert_variable_field(self):
        info = self._store()
        if not info:
            self._error("Import data first, then choose a variable field.")
            self.tabs.setCurrentIndex(0)
            return
        field, ok = QInputDialog.getItem(self, "Insert variable field", "Data field",
                                         info["metadata"]["fields"], 0, False)
        if ok:
            self.add_field(field, 20, 20)

    def insert_field_into_text(self):
        info = self._store()
        if not info or not self.properties.element:
            self._error("Import data and select a text object first.")
            return
        field, ok = QInputDialog.getItem(self, "Insert data field", "Data field",
                                         info["metadata"]["fields"], 0, False)
        if ok:
            cursor = self.properties.content.textCursor()
            cursor.insertText("{{" + field + "}}")
            self.properties.content.setTextCursor(cursor)

    def _remember_project(self, path):
        recent = self.preferences.value("recent_projects", [], type=list)
        values = [str(path)] + [value for value in recent if value != str(path)]
        self.preferences.setValue("recent_projects", values[:8])
        self._refresh_recent()

    def _refresh_recent(self):
        self.recent_menu.clear()
        for value in self.preferences.value("recent_projects", [], type=list):
            item = self.recent_menu.addAction(
                Path(value).name, lambda checked=False, path=value: self.open_project_path(path))
            item.setToolTip(value)
            item.setStatusTip(value)
        self.recent_menu.setEnabled(bool(self.recent_menu.actions()))

    def open_project_path(self, path):
        self.open_project(path=path)

    def review_failed_object(self):
        self.tabs.setCurrentIndex(1)
        if self.failed_record:
            self.record.setValue(self.failed_record)
        if self.failed_object:
            index = next((i for i, page in enumerate(self.template.pages)
                          if any(e.id == self.failed_object for e in page.elements)), None)
            if index is not None:
                self.select_template_page(index)
            self.canvas.select_ids([self.failed_object])
            self.properties_scroll.setVisible(True)
            self.actions["properties"].setChecked(True)
        self.message.setText("Review the selected object's font/content, then preview the failed record.")

    def open_report_folder(self):
        if self.last_report_dir:
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_report_dir))

    def show_shortcuts(self):
        QMessageBox.information(self, "Document Designer shortcuts",
            "Ctrl+N / O / S: New / Open / Save\nCtrl+Shift+S: Save as\n"
            "Ctrl+Z / Y: Undo / Redo\nCtrl+C / V / X / D: Copy / Paste / Cut / Duplicate\n"
            "Ctrl+A: Select all objects (canvas)\nArrow keys: move 0.5 mm; Shift: 5 mm\n"
            "Ctrl+mouse wheel: zoom; Space+drag: pan\nCtrl+0: fit page\n"
            "Alt+PgUp / PgDown: previous / next template page\n"
            "Ctrl+I: import data; F5: preview; Ctrl+Shift+G: generate PDF")

    def changeEvent(self, event):
        super().changeEvent(event)
        from PyQt6.QtCore import QEvent
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange):
            for value in getattr(self, "actions", {}).values():
                symbol = value.property("designer_icon")
                if symbol:
                    value.setIcon(icon(symbol))
            if hasattr(self, "barcode_button"):
                self.barcode_button.setIcon(icon("scan"))

    def _toolbar_font_size(self):
        if self.properties.element:
            self.properties.numbers["font_size"].setValue(self.font_size_tool.value())
            self.properties.apply()
