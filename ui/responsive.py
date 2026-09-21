"""Screen-bounded dialogs with scrollable content and reachable actions."""
from PyQt6.QtCore import QRect, Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def available_area(widget):
    screen = widget.screen() or QApplication.primaryScreen()
    return screen.availableGeometry() if screen else QRect(0, 0, 1024, 768)


def fit_window(widget, area=None):
    """Qt screen geometry is in logical pixels, including Windows scaling."""
    area = available_area(widget) if area is None else area
    margin_x = max(12, widget.frameGeometry().width() - widget.width() + 12)
    margin_y = max(40, widget.frameGeometry().height() - widget.height() + 12)
    width, height = max(200, area.width() - margin_x), max(160, area.height() - margin_y)
    widget.setMinimumSize(min(420, width), min(280, height))
    widget.resize(min(widget.width(), width), min(widget.height(), height))
    frame = widget.frameGeometry()
    x = min(max(frame.left(), area.left() + 6), area.right() - frame.width() - 5)
    y = min(max(frame.top(), area.top() + 6), area.bottom() - frame.height() - 5)
    widget.move(x, y)


def scroll_container(content, parent=None):
    scroll = QScrollArea(parent)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidgetResizable(True)
    scroll.setMinimumSize(0, 0)
    scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    scroll.setWidget(content)
    return scroll


def reveal_widget(widget):
    """Reveal focused controls through nested scroll areas, inside out."""
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QScrollArea):
            parent.ensureWidgetVisible(widget, 12, 12)
        parent = parent.parentWidget()


class ResponsiveDialog(QDialog):
    """Preserve original layouts; give overflow a viewport instead of clipping."""
    def _prepare_responsive(self):
        if hasattr(self, "_responsive_scroll") or self.layout() is None:
            return
        original = self.layout()
        preferred = self.size().expandedTo(original.sizeHint())
        content = QWidget()
        content.setObjectName("dialogScrollableContent")
        # Qt transfers the existing layout and reparents its widgets. Subclass
        # references to that layout remain valid for later dynamic updates.
        content.setLayout(original)
        original.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        footer = None
        if original.count():
            item = original.itemAt(original.count() - 1)
            if isinstance(item.widget(), (QDialogButtonBox, QPushButton)):
                footer = original.takeAt(original.count() - 1).widget()
            elif item.layout() is not None:
                row = item.layout()
                widgets = [row.itemAt(i).widget() for i in range(row.count())]
                if any(isinstance(w, QPushButton) for w in widgets) and all(
                    w is None or isinstance(w, (QPushButton, QDialogButtonBox)) for w in widgets
                ):
                    original.takeAt(original.count() - 1)
                    footer = QWidget()
                    footer.setLayout(row)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        self._responsive_scroll = scroll_container(content, self)
        self._responsive_scroll.setObjectName("dialogContentScroll")
        outer.addWidget(self._responsive_scroll, 1)
        self._responsive_footer = footer
        if footer is not None:
            # Wide action rows stay reachable too, without scrolling the body
            # back to the bottom to find Apply / Save / Cancel.
            footer_scroll = scroll_container(footer, self)
            footer_scroll.setObjectName("dialogFooterScroll")
            footer_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            footer_scroll.setFixedHeight(footer.sizeHint().height() + 22)
            outer.addWidget(footer_scroll)
        self.resize(preferred)
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._reveal_focus)

    def _reveal_focus(self, old, current):
        if current is not None and self.isAncestorOf(current):
            reveal_widget(current)

    def _fit_screen(self):
        self._prepare_responsive()
        fit_window(self)

    def showEvent(self, event):
        self._fit_screen()
        super().showEvent(event)
        handle = self.windowHandle()
        if handle is not None and not getattr(self, "_screen_connected", False):
            self._screen_connected = True
            handle.screenChanged.connect(self._watch_screen)
            self._watch_screen(handle.screen())

    def _watch_screen(self, screen):
        previous = getattr(self, "_watched_screen", None)
        if previous is not None:
            try:
                previous.availableGeometryChanged.disconnect(self._screen_geometry_changed)
            except (RuntimeError, TypeError):
                pass
        self._watched_screen = screen
        if screen is not None:
            screen.availableGeometryChanged.connect(self._screen_geometry_changed)
        self._screen_geometry_changed()

    def _screen_geometry_changed(self, *args):
        QTimer.singleShot(0, self._fit_screen)
