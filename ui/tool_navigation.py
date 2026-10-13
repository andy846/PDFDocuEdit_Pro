"""Reusable presentation widgets for the PDF tool navigation.

Tool identity, availability, routing and shortcut ownership remain in SidePanel.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .motion import MotionNavButton


class ToolNavButton(MotionNavButton):
    """Keep the full accessible label while painting text that fits the sidebar."""

    def __init__(self, label: str, parent=None):
        self.full_label = label
        self.compact = False
        super().__init__(label, parent=parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(label)

    def sizeHint(self):
        return QSize(160, super().sizeHint().height())

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def set_compact(self, compact: bool):
        self.compact = compact
        self.setProperty("collapsed", compact)
        self._fit_label()

    def _fit_label(self):
        self.setText(
            ""
            if self.compact
            else self.fontMetrics().elidedText(
                self.full_label, Qt.TextElideMode.ElideRight, max(0, self.width() - 56)
            )
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_label()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._fit_label()


class ToolPopup(QFrame):
    """Screen-bounded, searchable tool list. Opened by click, never by hover."""

    toolRequested = pyqtSignal(str)

    def __init__(self, title: str, entries, sources, matcher, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("sidebarToolPopup")
        self.setAccessibleName(title)
        self._matcher = matcher
        self._entries = entries
        self._sources = sources
        self.buttons = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        heading = QLabel(title)
        heading.setObjectName("sidebarTitle")
        layout.addWidget(heading)
        self.search = QLineEdit()
        self.search.setObjectName("sidebarSearch")
        self.search.setPlaceholderText("Search tools…")
        self.search.setAccessibleName("Search tools")
        self.search.setClearButtonEnabled(True)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("sidebarScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        rows = QVBoxLayout(content)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(2)
        for item in entries:
            button = ToolNavButton(item.label)
            button.setObjectName("sidebarNavButton")
            button.installEventFilter(self)
            button.clicked.connect(lambda _=False, key=item.key: self._activate(key))
            rows.addWidget(button)
            self.buttons[item.key] = button
        self.empty = QLabel("No matching tools")
        self.empty.setWordWrap(True)
        rows.addWidget(self.empty)
        rows.addStretch()
        self.scroll.setWidget(content)
        layout.addWidget(self.scroll, 1)
        self.search.textChanged.connect(self.filter_tools)
        self.refresh()
        self.filter_tools("")

    def refresh(self):
        for key, button in self.buttons.items():
            source = self._sources[key]
            button.setEnabled(source.isEnabled())
            button.setIcon(source.icon())
            button.setToolTip(source.toolTip())
            button.setAccessibleDescription(source.toolTip())
            button.setProperty("active", source.property("active"))
            button.set_animations_enabled(False)
            button.style().unpolish(button)
            button.style().polish(button)

    def filter_tools(self, query):
        matches = 0
        for item in self._entries:
            visible = self._matcher(item.key, query)
            self.buttons[item.key].setVisible(visible)
            matches += int(visible)
        self.empty.setVisible(not matches)

    def open_at(self, anchor: QWidget):
        origin = anchor.mapToGlobal(QPoint(anchor.width(), 0))
        screen = QApplication.screenAt(origin) or anchor.screen()
        area = screen.availableGeometry()
        width = min(380, area.width())
        height = min(500, area.height(), 114 + len(self._entries) * 44)
        self.resize(width, height)
        x = min(max(area.left(), origin.x()), area.right() - width + 1)
        y = min(max(area.top(), origin.y()), area.bottom() - height + 1)
        self.move(x, y)
        self._anchor = anchor
        self.show()
        # Some window systems adjust a popup's origin on its first show.
        frame = self.frameGeometry()
        dx = max(0, area.left() - frame.left()) - max(0, frame.right() - area.right())
        dy = max(0, area.top() - frame.top()) - max(0, frame.bottom() - area.bottom())
        if dx or dy:
            self.move(self.pos() + QPoint(dx, dy))
        self.search.setFocus()

    def hideEvent(self, event):
        super().hideEvent(event)
        anchor = getattr(self, "_anchor", None)
        if anchor is not None and anchor.isVisible():
            anchor.setFocus(Qt.FocusReason.PopupFocusReason)

    def _activate(self, key):
        if not self._sources[key].isEnabled():
            return
        self.hide()
        self.toolRequested.emit(key)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.hide()
                return True
            choices = [b for b in self.buttons.values() if not b.isHidden() and b.isEnabled()]
            if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down) and choices:
                step = 1 if event.key() == Qt.Key.Key_Down else -1
                index = choices.index(watched) if watched in choices else (-1 if step == 1 else 0)
                button = choices[(index + step) % len(choices)]
                button.setFocus()
                self.scroll.ensureWidgetVisible(button)
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if watched in choices:
                    watched.click()
                elif watched is self.search and choices:
                    choices[0].click()
                return True
        return super().eventFilter(watched, event)


class FavouritesDialog(QDialog):
    """Explicit add/remove/order controls with a maximum of eight pinned tools."""

    def __init__(self, items, favourites, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit favourite tools")
        area = (parent.screen() if parent is not None else QApplication.primaryScreen()).availableGeometry()
        self.resize(min(620, area.width() - 32), min(460, area.height() - 32))
        self._items = items
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        note = QLabel("Choose up to 8 tools. Their order is shared by the expanded sidebar and compact rail.")
        note.setWordWrap(True)
        layout.addWidget(note)
        columns = QHBoxLayout()
        if area.width() < 600:
            columns.setDirection(QHBoxLayout.Direction.TopToBottom)
        layout.addLayout(columns, 1)
        self.available = QListWidget()
        self.available.setMinimumWidth(0)
        self.available.setAccessibleName("Available tools")
        self.selected = QListWidget()
        self.selected.setMinimumWidth(0)
        self.selected.setAccessibleName("Favourite tools in display order")
        for view, title in ((self.available, "Available tools"), (self.selected, "Favourites")):
            box = QVBoxLayout()
            view.setTextElideMode(Qt.TextElideMode.ElideRight)
            view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            box.addWidget(QLabel(title))
            box.addWidget(view)
            columns.addLayout(box)
        for key in favourites:
            self._append(self.selected, key)
        for key in sorted(items, key=lambda k: items[k].label.casefold()):
            if key not in favourites:
                self._append(self.available, key)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        controls = QGridLayout()
        actions = (
            ("Add →", self.add_tool),
            ("Remove", self.remove_tool),
            ("Move up", lambda: self.move_tool(-1)),
            ("Move down", lambda: self.move_tool(1)),
        )
        for index, (label, handler) in enumerate(actions):
            button = QPushButton(label)
            button.clicked.connect(handler)
            controls.addWidget(button, index // 2, index % 2)
        outer.addLayout(controls)
        self.available.itemDoubleClicked.connect(lambda _item: self.add_tool())
        self.selected.itemDoubleClicked.connect(lambda _item: self.remove_tool())
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _append(self, view, key):
        row = QListWidgetItem(self._items[key].label)
        row.setData(Qt.ItemDataRole.UserRole, key)
        row.setToolTip(self._items[key].label)
        view.addItem(row)

    def keys(self):
        return [self.selected.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.selected.count())]

    def add_tool(self):
        if self.selected.count() >= 8:
            self.message.setText("A maximum of 8 favourite tools can be pinned.")
            return
        row = self.available.currentRow()
        if row >= 0:
            item = self.available.takeItem(row)
            self.selected.addItem(item)
            self.selected.setCurrentItem(item)
            self.message.clear()

    def remove_tool(self):
        row = self.selected.currentRow()
        if row >= 0:
            self.available.addItem(self.selected.takeItem(row))
            self.message.clear()

    def move_tool(self, offset):
        row = self.selected.currentRow()
        target = row + offset
        if row >= 0 and 0 <= target < self.selected.count():
            self.selected.insertItem(target, self.selected.takeItem(row))
            self.selected.setCurrentRow(target)
