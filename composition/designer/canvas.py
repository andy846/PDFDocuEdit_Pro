"""Millimetre designer geometry over the shared PDF renderer's preview."""
from __future__ import annotations

import copy

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDrag, QKeySequence, QPen, QPixmap
from PyQt6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QListWidget,
)


class FieldList(QListWidget):
    def startDrag(self, actions):
        item = self.currentItem()
        if item is None:
            return
        from PyQt6.QtCore import QMimeData
        mime = QMimeData()
        mime.setData("application/x-pdc-field", item.text().encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class ElementItem(QGraphicsRectItem):
    def __init__(self, element, canvas):
        super().__init__(0, 0, element.width_mm, element.height_mm)
        self.element = element
        self.canvas = canvas
        self.setPos(element.x_mm, element.y_mm)
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setZValue(2)
        pen = QPen(QColor("#4b91d8"), 1, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setToolTip(element.type + ": " + element.value)
        self.resizing = False

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        if self.isSelected():
            painter.fillRect(QRectF(self.rect().width()-2, self.rect().height()-2, 2, 2),
                             QColor("#2266aa"))

    def mousePressEvent(self, event):
        self.canvas.before = self.canvas.snapshot()
        self.resizing = (event.pos() - self.rect().bottomRight()).manhattanLength() < 5
        self.anchor = event.scenePos()
        self.original = QRectF(self.rect())
        if self.resizing:
            self.setSelected(True)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.resizing:
            delta = event.scenePos() - self.anchor
            width = min(self.canvas.page_width-self.pos().x(), max(0.1, self.original.width()+delta.x()))
            height = min(self.canvas.page_height-self.pos().y(), max(0.1, self.original.height()+delta.y()))
            self.setRect(0, 0, width, height)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if not self.resizing:
            super().mouseReleaseEvent(event)
        if self.canvas.snap_enabled:
            originals = {element["id"]: element for element in self.canvas.before["elements"]}
            if self.resizing:
                width = max(.1, min(self.canvas.page_width-self.pos().x(),
                                   round(self.rect().width()/5)*5))
                height = max(.1, min(self.canvas.page_height-self.pos().y(),
                                    round(self.rect().height()/5)*5))
                self.setRect(0, 0, width, height)
            else:
                origin = originals[self.element.id]
                dx = round(self.pos().x()/5)*5-origin["x_mm"]
                dy = round(self.pos().y()/5)*5-origin["y_mm"]
                for selected in self.canvas.element_items:
                    if selected.isSelected():
                        original = originals[selected.element.id]
                        selected.setPos(original["x_mm"]+dx, original["y_mm"]+dy)
        for item in self.canvas.element_items:
            x = max(0, min(self.canvas.page_width-item.rect().width(), item.pos().x()))
            y = max(0, min(self.canvas.page_height-item.rect().height(), item.pos().y()))
            x, y = round(x, 2), round(y, 2)
            width, height = round(item.rect().width(), 2), round(item.rect().height(), 2)
            item.setRect(0, 0, width, height)
            item.setPos(x, y)
            item.element.x_mm, item.element.y_mm = x, y
            item.element.width_mm, item.element.height_mm = width, height
        self.canvas.editCommitted.emit(self.canvas.before, self.canvas.snapshot())
        self.resizing = False


class Canvas(QGraphicsView):
    selectionChanged = pyqtSignal(str)
    editCommitted = pyqtSignal(dict, dict)
    fieldDropped = pyqtSignal(str, float, float)
    command = pyqtSignal(str)
    zoomChanged = pyqtSignal(float)
    pointerMoved = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene_model = QGraphicsScene(self)
        self.setScene(self.scene_model)
        self.setBackgroundBrush(QColor("#59616b"))
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.scene_model.selectionChanged.connect(self._selected)
        self.element_items = []
        self.template = None
        self.preview_item = None
        self.page_width, self.page_height = 210, 297
        self.grid_visible = False
        self.snap_enabled = False
        self.setMouseTracking(True)
        self.space = False
        self.mode_preview = False
        self.design_selection = []

    def snapshot(self):
        return copy.deepcopy(self.template.to_dict())

    def set_template(self, template, selected=None):
        self.template = template
        self.page_width, self.page_height = template.width_mm, template.height_mm
        self.scene_model.blockSignals(True)
        self.scene_model.clear()
        self.preview_item = None
        page = self.scene_model.addRect(0, 0, template.width_mm, template.height_mm,
                                       QPen(Qt.PenStyle.NoPen), QColor("white"))
        page.setZValue(-2)
        self.element_items = [ElementItem(element, self) for element in template.elements]
        selected_ids = set(selected if isinstance(selected, list) else [selected])
        for item in self.element_items:
            self.scene_model.addItem(item)
            item.setVisible(not self.mode_preview)
            item.setSelected(item.element.id in selected_ids)
        self.setSceneRect(-15, -15, template.width_mm+30, template.height_mm+30)
        self.scene_model.blockSignals(False)

    def set_preview(self, image):
        if self.preview_item:
            self.scene_model.removeItem(self.preview_item)
            self.preview_item = None
        if not image:
            return
        pixmap = QPixmap(image)
        if pixmap.isNull():
            return
        item = QGraphicsPixmapItem(pixmap)
        item.setScale(self.page_width / pixmap.width())
        item.setZValue(-1)
        self.scene_model.addItem(item)
        self.preview_item = item

    def set_preview_mode(self, enabled):
        previous = self.mode_preview
        if enabled and not previous:
            self.design_selection = self.selected_ids()
        self.mode_preview = enabled
        for item in self.element_items:
            item.setVisible(not enabled)
        if previous and not enabled:
            self.select_ids(self.design_selection)

    def fit_page(self):
        self.fitInView(QRectF(-8, -8, self.page_width+16, self.page_height+16),
                       Qt.AspectRatioMode.KeepAspectRatio)
        self.zoomChanged.emit(self.transform().m11()/(96/25.4))

    def set_zoom(self, value):
        if not .1 <= value <= 8:
            raise ValueError("Zoom must be between 10% and 800%.")
        self.resetTransform()
        self.scale(value*96/25.4, value*96/25.4)
        self.zoomChanged.emit(value)

    def zoom_by(self, factor):
        self.set_zoom(max(.1, min(8, self.transform().m11()/(96/25.4)*factor)))

    def set_grid(self, enabled):
        self.grid_visible = bool(enabled)
        self.viewport().update()

    def set_snap(self, enabled):
        self.snap_enabled = bool(enabled)

    def select_ids(self, ids):
        selected = set(ids)
        self.scene_model.blockSignals(True)
        for item in self.element_items:
            item.setSelected(item.element.id in selected)
        self.scene_model.blockSignals(False)
        self._selected()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        point = self.mapToScene(event.position().toPoint())
        if 0 <= point.x() <= self.page_width and 0 <= point.y() <= self.page_height:
            self.pointerMoved.emit(point.x(), point.y())

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        if not self.grid_visible or self.mode_preview:
            return
        painter.save()
        painter.setClipRect(QRectF(0, 0, self.page_width, self.page_height))
        pen = QPen(QColor(80, 115, 145, 65), 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        from PyQt6.QtCore import QLineF
        for x in range(0, int(self.page_width)+1, 5):
            painter.drawLine(QLineF(x, 0, x, self.page_height))
        for y in range(0, int(self.page_height)+1, 5):
            painter.drawLine(QLineF(0, y, self.page_width, y))
        painter.restore()

    def selected_ids(self):
        return [item.element.id for item in self.element_items if item.isSelected()]

    def _selected(self):
        ids = self.selected_ids()
        self.selectionChanged.emit(ids[0] if len(ids) == 1 else "")

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            scale = 1.15 if event.angleDelta().y() > 0 else 1/1.15
            if 0.3 < self.transform().m11()*scale < 40:
                self.scale(scale, scale)
                self.zoomChanged.emit(self.transform().m11()/(96/25.4))
            event.accept()
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Space:
            self.space = True
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            event.accept()
            return
        commands = {QKeySequence.StandardKey.Copy: "copy", QKeySequence.StandardKey.Paste: "paste",
                    QKeySequence.StandardKey.Delete: "delete"}
        for shortcut, name in commands.items():
            if event.matches(shortcut):
                self.command.emit(name)
                return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_D:
            self.command.emit("duplicate")
            return
        moves = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
                 Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if key in moves and not self.mode_preview:
            before = self.snapshot()
            dx, dy = moves[key]
            step = 5 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0.5
            for item in self.element_items:
                if item.isSelected():
                    item.element.x_mm = min(self.page_width-item.element.width_mm,
                                            max(0, item.element.x_mm+dx*step))
                    item.element.y_mm = min(self.page_height-item.element.height_mm,
                                            max(0, item.element.y_mm+dy*step))
                    item.setPos(item.element.x_mm, item.element.y_mm)
            self.editCommitted.emit(before, self.snapshot())
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.space = False
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            return
        super().keyReleaseEvent(event)

    def dragEnterEvent(self, event):
        if not self.mode_preview and event.mimeData().hasFormat("application/x-pdc-field"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat("application/x-pdc-field") and not self.mode_preview:
            point = self.mapToScene(event.position().toPoint())
            self.fieldDropped.emit(bytes(event.mimeData().data("application/x-pdc-field")).decode("utf-8"),
                                   max(0, point.x()), max(0, point.y()))
            event.acceptProposedAction()
