"""Solid popup bodies with per-pixel antialiased edges."""
from PyQt6.QtCore import QEvent, QObject, QRectF, Qt
from PyQt6.QtGui import QPainter, QPainterPath, QRegion
from PyQt6.QtWidgets import QAbstractItemView, QComboBox, QFrame, QLabel, QMenu, QStyle, QStyleOption, QWidget

from .tokens import R


class _PopupSurfaceEvents(QObject):
    _events = {
        QEvent.Type.Show, QEvent.Type.Resize, QEvent.Type.Paint,
        QEvent.Type.StyleChange, QEvent.Type.PaletteChange,
        QEvent.Type.DevicePixelRatioChange,
    }

    def prepare_menu(self):
        self.prepare(self.sender())

    def prepare(self, widget):
        """Configure only a hidden popup, outside style polish/show handling.

        A private Qt widget may lose its temporary Python wrapper. Keep state
        on the QObject itself rather than on that wrapper; never retain it.
        """
        if not isinstance(widget, QWidget) or widget.isVisible():
            return
        if widget.property('_popup_alpha') or widget.property('_popup_preparing'):
            return
        is_tip = (isinstance(widget, QLabel)
                  and widget.metaObject().className() == 'QTipLabel')
        if not (isinstance(widget, QMenu) or is_tip or (
            isinstance(widget, QFrame) and isinstance(widget.parentWidget(), QComboBox)
            and widget.windowType() == Qt.WindowType.Popup
        )):
            return
        widget.setProperty('_popup_preparing', True)
        try:
            # Windows needs a frameless native surface for per-pixel alpha.
            # Preserve Popup/ToolTip type; never change an already-open window.
            # Set alpha BEFORE a flag change can recreate an existing HWND;
            # otherwise its first native surface retains an opaque format.
            widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            widget.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            widget.setProperty('_popup_alpha', True)
        finally:
            widget.setProperty('_popup_preparing', False)

    def eventFilter(self, widget, event):
        if isinstance(widget, QComboBox):
            if event.type() == QEvent.Type.Show:
                # The control is ready, while its private dropdown is hidden.
                self.prepare(widget.view().window())
            return False
        if event.type() not in self._events or not isinstance(widget, QWidget):
            return False
        # Hidden menus may be only partly constructed or undergoing global QSS
        # teardown. Shape them on Show, not while Qt polishes the widget tree.
        if widget.property('_popup_shape_busy'):
            return False
        kind = None
        if isinstance(widget, QMenu) and widget.windowType() == Qt.WindowType.Popup:
            kind = 'menu'
        elif isinstance(widget, QLabel):
            if widget.objectName() == 'qtooltip_label' and widget.metaObject().className() == 'QTipLabel':
                kind = 'tooltip'
        elif (isinstance(widget, QFrame)
              and isinstance(widget.parentWidget(), QComboBox)
              and widget.windowType() == Qt.WindowType.Popup
              and widget.findChild(QAbstractItemView) is not None):
            kind = 'combo'
        if kind is None or widget.width() <= 0 or widget.height() <= 0:
            return False
        if event.type() != QEvent.Type.Show and not widget.isVisible():
            return False
        widget.setProperty('_popup_shape_busy', True)
        try:
            if kind == 'combo':
                from .components import combo_popup_style
                surface = combo_popup_style()
                if widget.styleSheet() != surface:
                    widget.setProperty('pdfdocueditPopupSurface', kind)
                    widget.setStyleSheet(surface)
                    if widget.layout() is not None:
                        widget.layout().setContentsMargins(1, 1, 1, 1)
            if widget.property('_popup_alpha'):
                # Qt can reinstall a tooltip style mask during resize. A binary
                # mask cuts off the alpha fringe and produces visible stairs.
                if not widget.mask().isEmpty():
                    widget.clearMask()
                if kind == 'combo' and event.type() == QEvent.Type.Paint:
                    # Translucent QFrames skip QWidget's automatic background.
                    # Paint the existing QSS surface explicitly, including for
                    # editable combos whose delegate does not fill every row.
                    option = QStyleOption()
                    option.initFrom(widget)
                    painter = QPainter(widget)
                    try:
                        widget.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget,
                                                     option, painter, widget)
                    finally:
                        painter.end()
                    return True
                return False
            # Safe coarse fallback for a popup first encountered while open:
            # configuring alpha then could rebuild its native window.
            key = f'{widget.width()}:{widget.height()}:{R.LG}:{widget.devicePixelRatioF()}'
            if widget.property('_popup_shape_key') != key:
                path = QPainterPath()
                path.addRoundedRect(QRectF(widget.rect()), R.LG, R.LG)
                widget.setProperty('_popup_shape_region', QRegion(path.toFillPolygon().toPolygon()))
                widget.setProperty('_popup_shape_key', key)
            region = widget.property('_popup_shape_region')
            # Qt can replace a menu/tooltip mask in its resize handler. Paint
            # is the last opportunity to restore it before drawing the surface.
            if widget.mask() != region:
                widget.setMask(region)
        finally:
            widget.setProperty('_popup_shape_busy', False)
        return False


class PopupShapes(QObject):
    """Application-owned coordinator for widget-owned popup filters.

    QApplication-wide Python filtering can crash during native Qt teardown.
    The retained proxy registers surfaces during polish; shaping waits for Show.
    Filters must outlive their watched widgets until each widget is destroyed;
    parenting one shared filter to QApplication can retire it too early during
    native application teardown while hidden windows still exist.
    """
    def __init__(self, parent):
        super().__init__(parent)
        self.surfaces = _PopupSurfaceEvents(self)

    def register(self, widget):
        if isinstance(widget, (QMenu, QComboBox)) or (
            isinstance(widget, QFrame) and isinstance(widget.parentWidget(), QComboBox)
        ) or (
            isinstance(widget, QLabel)
            and widget.windowType() == Qt.WindowType.ToolTip
            and widget.metaObject().className() == 'QTipLabel'
        ):
            # Reinstalling the same filter only changes its order in Qt; avoid
            # even that work when stylesheet/theme polish repeats.
            if not widget.property('_popup_shape_registered'):
                events = _PopupSurfaceEvents(widget)
                widget.installEventFilter(events)
                # A private Qt popup can lose its temporary Python wrapper.
                # A tuple QVariant retains the Python virtual-method owner on
                # the native QObject, without retaining the watched widget.
                widget.setProperty('_popup_shape_events', (events,))
                widget.setProperty('_popup_shape_registered', True)
                if isinstance(widget, QMenu):
                    widget.aboutToShow.connect(events.prepare_menu)


def install_popup_shapes(app):
    """Application ownership avoids timers and callbacks to deleted popups."""
    if getattr(app, '_pdfdocuedit_popup_shapes', None) is None:
        coordinator = PopupShapes(app)
        app._pdfdocuedit_popup_shapes = coordinator
