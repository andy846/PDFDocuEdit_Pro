"""Paper-coordinate rulers for the PDF viewport; never render or modify a PDF."""
from __future__ import annotations

import math

from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, QSizeF, Qt, QTimer
from PyQt6.QtGui import QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import QLabel, QWidget

MM_PER_POINT = 25.4 / 72


def major_interval(pixels_per_mm):
    """Readable labels at all zooms, with a bounded number of paint operations."""
    minimum = 65 / max(pixels_per_mm, .001)
    power = 10 ** math.floor(math.log10(minimum))
    return next(value * power for value in (1, 2, 5, 10) if value * power >= minimum)


class PaperRuler(QWidget):
    def __init__(self, controller, horizontal):
        super().__init__(controller.canvas)
        self.controller, self.horizontal = controller, horizontal
        self.setAccessibleName("Paper horizontal ruler" if horizontal else "Paper vertical ruler")
        self.setToolTip("PDF paper size; calibrated measurement distances are shown separately.")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def axis(self):
        state = self.controller.state
        if state is None:
            return None
        rect, width_mm, height_mm = state
        return (rect.left(), rect.width()/width_mm, width_mm) if self.horizontal else (
            rect.top(), rect.height()/height_mm, height_mm)

    def position_mm(self, position):
        axis = self.axis()
        return None if axis is None else (position-axis[0])/axis[1]

    def update_marker(self, before, after):
        for point in (before, after):
            if point is not None:
                position = round(point.x() if self.horizontal else point.y())
                if self.horizontal:
                    self.update(position-2, 0, 5, self.height())
                else:
                    self.update(0, position-2, self.width(), 5)

    def paintEvent(self, event):
        painter = QPainter(self)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.window())
        painter.setPen(palette.mid().color())
        horizontal = self.horizontal
        length = self.width() if horizontal else self.height()
        edge = self.height()-1 if horizontal else self.width()-1
        painter.drawLine(0, edge, length, edge) if horizontal else painter.drawLine(edge, 0, edge, length)
        axis = self.axis()
        if axis is None:
            return
        origin, scale, extent = axis
        major = major_interval(scale)
        step = major/10
        first = max(0, math.ceil((-origin)/scale/step))
        last = min(math.floor(extent/step), math.floor((length-origin)/scale/step))
        painter.setPen(palette.windowText().color())
        metrics = QFontMetricsF(painter.font())
        for index in range(first, last+1):
            value = index*step
            position = origin+value*scale
            large = index % 10 == 0
            tick = 10 if large else 6 if index % 5 == 0 else 3
            if horizontal:
                painter.drawLine(QPointF(position, edge), QPointF(position, edge-tick))
            else:
                painter.drawLine(QPointF(edge, position), QPointF(edge-tick, position))
            if large:
                label = f"{value/(10 if self.controller.canvas.measure_unit == 'cm' else 1):g}"
                if horizontal:
                    painter.drawText(QPointF(position+3, metrics.ascent()+2), label)
                else:
                    painter.save()
                    painter.translate(3+metrics.ascent(), position-3)
                    painter.rotate(-90)
                    painter.drawText(QPointF(0, 0), label)
                    painter.restore()
        pointer = self.controller.pointer
        if pointer is not None:
            position = pointer.x() if horizontal else pointer.y()
            if origin <= position <= origin+extent*scale:
                painter.setPen(QPen(palette.highlight().color(), 1))
                if horizontal:
                    painter.drawLine(QPointF(position, 0), QPointF(position, edge))
                else:
                    painter.drawLine(QPointF(0, position), QPointF(edge, position))


class PdfRulers(QObject):
    LEFT = 40
    TOP = 30

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.enabled = False
        self.pointer = None
        self.reference_page = None
        self.state = None
        self._pending_pointer = None
        self.pointer_timer = QTimer(self)
        self.pointer_timer.setSingleShot(True)
        self.pointer_timer.setInterval(16)
        self.pointer_timer.timeout.connect(self.flush_pointer)
        self.horizontal = PaperRuler(self, True)
        self.vertical = PaperRuler(self, False)
        self.corner = QLabel(canvas)
        self.corner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.corner.setAccessibleName("Ruler reference page and paper unit")
        for widget in (self.horizontal, self.vertical, self.corner):
            widget.hide()
        canvas.viewport().installEventFilter(self)
        canvas._pager.setMouseTracking(True)
        canvas._pager.installEventFilter(self)
        canvas.horizontalScrollBar().valueChanged.connect(self.refresh)
        canvas.verticalScrollBar().valueChanged.connect(self.refresh)
        canvas.pageChanged.connect(self.reset_pointer)
        canvas.zoomChanged.connect(self.reset_pointer)

    def register(self, overlay):
        overlay.installEventFilter(self)

    def reset_pointer(self, *_):
        self.pointer_timer.stop()
        self._pending_pointer = None
        self.pointer = None
        self.refresh()

    def flush_pointer(self):
        if not self.enabled:
            return
        before = self.pointer
        self.pointer = self._pending_pointer
        if (self.state is not None and self.pointer is not None
                and self.state[0].contains(QPointF(self.pointer))):
            # Same page: paint only old/new cursor strips. No geometry or labels.
            self.horizontal.update_marker(before, self.pointer)
            self.vertical.update_marker(before, self.pointer)
        else:
            self.refresh()

    def set_enabled(self, enabled):
        if self.enabled == enabled:
            return
        anchor = self.canvas._view_anchor()
        self.enabled = enabled
        self.pointer_timer.stop()
        self._pending_pointer = None
        self.pointer = None
        self.canvas._ruler_view_anchor = anchor if self.canvas._doc is not None else None
        self.canvas.setViewportMargins(self.LEFT if enabled else 0, self.TOP if enabled else 0, 0, 0)
        for widget in (self.horizontal, self.vertical, self.corner):
            widget.setVisible(enabled)
        if self.canvas._doc is not None:
            self.canvas._resize_timer.stop()
            self.canvas._apply_pending_relayout()
        self.refresh()

    def refresh(self, *_):
        if not self.enabled:
            return
        canvas = self.canvas
        viewport = canvas.viewport()
        vp = viewport.geometry()
        self.horizontal.setGeometry(vp.left(), vp.top()-self.TOP, vp.width(), self.TOP)
        self.vertical.setGeometry(vp.left()-self.LEFT, vp.top(), self.LEFT, vp.height())
        self.corner.setGeometry(vp.left()-self.LEFT, vp.top()-self.TOP, self.LEFT, self.TOP)
        page_num = canvas.current_page
        if self.pointer is not None:
            for number, view in canvas._page_views.items():
                if view.parentWidget() is not canvas._pager:
                    continue
                origin = view.overlay.mapTo(viewport, QPoint(0, 0))
                if QRectF(QPointF(origin), view.overlay.size().toSizeF()).contains(QPointF(self.pointer)):
                    page_num = number
                    break
            else:
                self.pointer = None
        self.reference_page = page_num if canvas._doc is not None else None
        view = canvas._page_views.get(page_num) if canvas._doc is not None else None
        if view is not None and view.parentWidget() is not canvas._pager:
            view = None
        if view is None:
            self.state = None
        else:
            overlay = view.overlay
            origin = overlay.mapTo(viewport, QPoint(0, 0))
            page_rect = overlay._page_rect
            # Use the PDF transform, not layout height (captions and pre-render
            # widget sizing can differ). This matches endpoint coordinates.
            size = QSizeF(page_rect.width/overlay._scale, page_rect.height/overlay._scale)
            self.state = (QRectF(QPointF(origin), size),
                          page_rect.width*MM_PER_POINT, page_rect.height*MM_PER_POINT)
        unit = canvas.measure_unit
        self.corner.setText(f"P{page_num+1}\n{unit}" if self.reference_page is not None else unit)
        self.corner.setToolTip(f"Page {page_num+1} · Paper coordinates ({unit})\n"
                               "Calibrated distances are shown on measurement lines.")
        self.horizontal.update()
        self.vertical.update()

    def eventFilter(self, obj, event):
        if self.enabled:
            if event.type() == QEvent.Type.MouseMove:
                self._pending_pointer = obj.mapTo(self.canvas.viewport(), event.position().toPoint())
                if not self.pointer_timer.isActive():
                    self.pointer_timer.start()
            elif event.type() == QEvent.Type.Leave:
                self.reset_pointer()
            elif event.type() == QEvent.Type.Resize:
                self.refresh()
        return False
