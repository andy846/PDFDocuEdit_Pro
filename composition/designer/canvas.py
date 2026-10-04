"""Millimetre designer geometry over the shared PDF renderer's preview."""
from __future__ import annotations

import copy
import math

from PyQt6.QtCore import QEvent, QLineF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDrag, QKeySequence, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QListWidget,
    QStyle,
    QStyleOptionGraphicsItem,
)

from composition.engine.preview_raster import screen_scale
from styles.theme import get_colors


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
        self.element, self.canvas = element, canvas
        self.setPos(element.x_mm, element.y_mm)
        self.setTransformOriginPoint(self.rect().center())
        self.setRotation(element.rotation_deg)
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setZValue(2)
        pen = QPen(QColor(get_colors()["primary"]), 1, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setToolTip(element.type + ": " + element.value)
        self.resizing = False

    def paint(self, painter, option, widget=None):
        plain = QStyleOptionGraphicsItem(option)
        plain.state &= ~QStyle.StateFlag.State_Selected
        super().paint(painter, plain, widget)
        if self.isSelected():
            painter.save()
            pen = QPen(QColor(get_colors()["primary"]), 1.5)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect())
            painter.fillRect(QRectF(self.rect().width()-2, self.rect().height()-2, 2, 2), QColor(get_colors()["primary"]))
            painter.restore()

    def mousePressEvent(self, event):
        if not self.canvas.editable:
            return super().mousePressEvent(event)
        if hasattr(self.canvas, "before_edit") and not self.canvas.before_edit():
            event.ignore()
            return
        self.canvas.before = self.canvas.snapshot()
        self.resizing = (event.pos() - self.rect().bottomRight()).manhattanLength() < 5
        self.anchor = event.scenePos()
        self.original = QRectF(self.rect())
        self.resize_top_left = self.mapToScene(self.rect().topLeft())
        if self.resizing:
            self.setSelected(True)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self.canvas.editable:
            return super().mouseMoveEvent(event)
        if self.resizing:
            delta = event.scenePos() - self.anchor
            angle = math.radians(self.rotation())
            dx = delta.x()*math.cos(angle)+delta.y()*math.sin(angle)
            dy = -delta.x()*math.sin(angle)+delta.y()*math.cos(angle)
            width, height = max(.1, self.original.width()+dx), max(.1, self.original.height()+dy)
            if self.canvas.snap_enabled and not event.modifiers() & Qt.KeyboardModifier.AltModifier:
                width, height = max(.1, round(width/5)*5), max(.1, round(height/5)*5)
            self.setRect(0, 0, width, height)
            self.setTransformOriginPoint(self.rect().center())
            self.setPos(self.pos()+self.resize_top_left-self.mapToScene(self.rect().topLeft()))
        else:
            super().mouseMoveEvent(event)
            self.canvas.snap_drag(self, event.modifiers())

    def mouseReleaseEvent(self, event):
        if not self.canvas.editable:
            return super().mouseReleaseEvent(event)
        if not self.resizing:
            super().mouseReleaseEvent(event)
        else:
            self.canvas.fit_resized_item(self)
        self.canvas.keep_group_on_page()
        targets = [self] if self.resizing else [item for item in self.canvas.element_items if item.isSelected()]
        for item in targets:
            item.element.x_mm, item.element.y_mm = round(item.pos().x(), 2), round(item.pos().y(), 2)
            item.element.width_mm, item.element.height_mm = round(item.rect().width(), 2), round(item.rect().height(), 2)
            item.setPos(item.element.x_mm, item.element.y_mm)
            item.setRect(0, 0, item.element.width_mm, item.element.height_mm)
            item.setTransformOriginPoint(item.rect().center())
        self.resizing = False
        self.canvas.guides = []
        self.canvas.viewport().update()
        self.canvas.editCommitted.emit(self.canvas.before, self.canvas.snapshot())


class Canvas(QGraphicsView):
    selectionChanged = pyqtSignal(str)
    editCommitted = pyqtSignal(dict, dict)
    fieldDropped = pyqtSignal(str, float, float)
    command = pyqtSignal(str)
    zoomChanged = pyqtSignal(float)
    previewScaleChanged = pyqtSignal()
    objectActivated = pyqtSignal()
    pointerMoved = pyqtSignal(float, float)
    measurementChanged = pyqtSignal(float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene_model = QGraphicsScene(self)
        self.setScene(self.scene_model)
        self.setBackgroundBrush(QColor(get_colors()["canvas"]))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing |
                            QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.scene_model.selectionChanged.connect(self._selected)
        self.element_items = []
        self.template = None
        self.preview_item = None
        self.page_item = None
        self.page_context = None
        self.page_width, self.page_height = 210, 297
        self._preview_scale = None
        self.grid_visible = False
        self.snap_enabled = False
        self.setMouseTracking(True)
        self.space = False
        self.mode_preview = False
        self.editable = True
        self.design_selection = []
        self.snap_guides_enabled = True
        self.guides = []
        self.measure_enabled = False
        self.measure_start = self.measure_end = None
        self.measuring = False
        from .rulers import Ruler
        self.horizontal_ruler, self.vertical_ruler = Ruler(self, True), Ruler(self, False)
        self.rulers_visible = True
        self.set_rulers(True)
        self.zoomChanged.connect(lambda *args: self.update_rulers())
        self.zoomChanged.connect(self._check_preview_scale)

    def preview_scale(self):
        points_per_mm = 72 / 25.4
        return screen_scale(self.page_width * points_per_mm, self.page_height * points_per_mm,
                            self.transform().m11() * self.viewport().devicePixelRatioF() / points_per_mm)

    def _check_preview_scale(self, *args):
        scale = self.preview_scale()
        if scale != self._preview_scale:
            self._preview_scale = scale
            self.previewScaleChanged.emit()

    def snapshot(self):
        return copy.deepcopy(self.template.to_dict())

    def set_template(self, template, selected=None, *, page_index=0, context=None):
        """Synchronize objects in place; ordinary edits never clear the scene."""
        self.template = template
        self.page_index = page_index
        spec = template.pages[page_index]
        self.page_width, self.page_height = spec.width_mm, spec.height_mm
        page_context = (context if context is not None else spec.id,
                        spec.background, spec.width_mm, spec.height_mm)
        if page_context != self.page_context:
            self.set_preview(None)
            self.measure_start = self.measure_end = None
        self.page_context = page_context
        existing = {item.element.id: item for item in self.element_items}
        selected_ids = set(selected if isinstance(selected, list) else
                           self.selected_ids() if selected is None else [selected])
        blocked = self.scene_model.signalsBlocked()
        self.scene_model.blockSignals(True)
        try:
            if self.page_item is None:
                self.page_item = self.scene_model.addRect(
                    0, 0, spec.width_mm, spec.height_mm,
                    QPen(Qt.PenStyle.NoPen), QColor("white"))
                self.page_item.setZValue(-2)
            else:
                self.page_item.setRect(0, 0, spec.width_mm, spec.height_mm)
            items = []
            for index, element in enumerate(spec.elements):
                item = existing.pop(element.id, None)
                if item is None:
                    item = ElementItem(element, self)
                    self.scene_model.addItem(item)
                else:
                    item.element = element
                    item.setRect(0, 0, element.width_mm, element.height_mm)
                    item.setTransformOriginPoint(item.rect().center())
                    item.setRotation(element.rotation_deg)
                    item.setPos(element.x_mm, element.y_mm)
                    item.setToolTip(element.type + ": " + element.value)
                item.setZValue(2 + index / max(1, len(spec.elements)))
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, self.editable and not self.mode_preview)
                item.setVisible(not self.mode_preview)
                item.setSelected(element.id in selected_ids)
                items.append(item)
            for item in existing.values():
                self.scene_model.removeItem(item)
            self.element_items = items
            bounds = QRectF(-15, -15, spec.width_mm+30, spec.height_mm+30)
            if self.sceneRect() != bounds:
                self.setSceneRect(bounds)
        finally:
            self.scene_model.blockSignals(blocked)
        self.guides = []
        self.update_rulers()
        self._check_preview_scale()

    def set_preview(self, image):
        if not image:
            if self.preview_item is not None:
                self.scene_model.removeItem(self.preview_item)
                self.preview_item = None
            return
        pixmap = QPixmap(image)
        if pixmap.isNull():
            return
        if self.preview_item is None:
            self.preview_item = QGraphicsPixmapItem()
            self.preview_item.setZValue(-1)
            self.preview_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.preview_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            self.scene_model.addItem(self.preview_item)
        self.preview_item.setPixmap(pixmap)
        self.preview_item.setScale(self.page_width / pixmap.width())

    def event(self, event):
        result = super().event(event)
        if event.type() == QEvent.Type.DevicePixelRatioChange and hasattr(self, "page_width"):
            self._check_preview_scale()
        return result

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange):
            self.setBackgroundBrush(QColor(get_colors()["canvas"]))
            for item in getattr(self, "element_items", ()):
                pen = item.pen()
                pen.setColor(QColor(get_colors()["primary"]))
                item.setPen(pen)
            self.update_rulers()

    def set_editable(self, enabled):
        self.editable = bool(enabled)
        for item in self.element_items:
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, self.editable and not self.mode_preview)

    def set_preview_mode(self, enabled):
        previous = self.mode_preview
        if enabled and not previous:
            self.design_selection = self.selected_ids()
        self.mode_preview = enabled
        self.set_editable(self.editable)
        for item in self.element_items:
            item.setVisible(not enabled)
        if previous and not enabled:
            self.select_ids(self.design_selection)

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        if self.editable and not self.mode_preview and self.selected_ids():
            self.objectActivated.emit()

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

    def set_snap_guides(self, enabled):
        self.snap_guides_enabled = bool(enabled)
        self.guides = []
        self.viewport().update()

    def set_rulers(self, enabled):
        self.rulers_visible = bool(enabled)
        size = 24 if enabled else 0
        self.setViewportMargins(size, size, 0, 0)
        self.horizontal_ruler.setVisible(enabled)
        self.vertical_ruler.setVisible(enabled)
        self.update_rulers()

    def update_rulers(self):
        if not hasattr(self, "horizontal_ruler"):
            return
        viewport = self.viewport().geometry()
        self.horizontal_ruler.setGeometry(viewport.left(), 0, viewport.width(), 24)
        self.vertical_ruler.setGeometry(0, viewport.top(), 24, viewport.height())
        self.horizontal_ruler.update()
        self.vertical_ruler.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_rulers()

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self.update_rulers()

    def set_measure(self, enabled):
        self.measure_enabled = bool(enabled)
        self.measure_start = self.measure_end = None
        self.measuring = False
        self.viewport().setCursor(Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor)
        self.viewport().update()

    def mousePressEvent(self, event):
        if self.measure_enabled and event.button() == Qt.MouseButton.LeftButton:
            self.measure_start = self.measure_end = self.mapToScene(event.position().toPoint())
            self.measuring = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self.measuring:
            self.measuring = False
            self.measure_end = self.mapToScene(event.position().toPoint())
            self.report_measurement()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def report_measurement(self):
        delta = self.measure_end-self.measure_start
        self.measurementChanged.emit(math.hypot(delta.x(), delta.y()), abs(delta.x()), abs(delta.y()))
        self.viewport().update()

    def group_bounds(self, items):
        rect = QRectF()
        for item in items:
            bounds = item.mapRectToScene(item.rect())
            rect = bounds if rect.isNull() else rect.united(bounds)
        return rect

    def keep_group_on_page(self):
        items = [item for item in self.element_items if item.isSelected()]
        if not items:
            return
        rect = self.group_bounds(items)
        dx = -rect.left() if rect.left() < 0 else min(0, self.page_width-rect.right())
        dy = -rect.top() if rect.top() < 0 else min(0, self.page_height-rect.bottom())
        dx, dy = max(dx, -min(item.pos().x() for item in items)), max(dy, -min(item.pos().y() for item in items))
        for item in items:
            item.moveBy(dx, dy)

    def fit_resized_item(self, item):
        top_left = item.mapToScene(item.rect().topLeft())
        bounds = item.mapRectToScene(item.rect())
        scale = min(1, self.page_width/bounds.width(), self.page_height/bounds.height())
        width, height = item.rect().width()*scale, item.rect().height()*scale
        item.setRect(0, 0, width, height)
        item.setTransformOriginPoint(item.rect().center())
        item.setPos(item.pos()+top_left-item.mapToScene(item.rect().topLeft()))

    def snap_drag(self, dragged, modifiers=Qt.KeyboardModifier.NoModifier):
        items = [item for item in self.element_items if item.isSelected()]
        self.guides = []
        if not items:
            return
        rect = self.group_bounds(items)
        threshold = 6/max(.01, self.transform().m11())
        targets_x, targets_y = [0, self.page_width/2, self.page_width], [0, self.page_height/2, self.page_height]
        for other in self.element_items:
            if other in items:
                continue
            bounds = other.mapRectToScene(other.rect())
            targets_x.extend((bounds.left(), bounds.center().x(), bounds.right()))
            targets_y.extend((bounds.top(), bounds.center().y(), bounds.bottom()))
        def nearest(anchors, targets):
            best = min(((target-anchor, target) for anchor in anchors for target in targets), key=lambda pair: abs(pair[0]))
            return best if abs(best[0]) <= threshold else None
        enabled = not modifiers & Qt.KeyboardModifier.AltModifier
        sx = nearest((rect.left(), rect.center().x(), rect.right()), targets_x) if self.snap_guides_enabled and enabled else None
        sy = nearest((rect.top(), rect.center().y(), rect.bottom()), targets_y) if self.snap_guides_enabled and enabled else None
        dx = sx[0] if sx else round(dragged.pos().x()/5)*5-dragged.pos().x() if self.snap_enabled and enabled else 0
        dy = sy[0] if sy else round(dragged.pos().y()/5)*5-dragged.pos().y() if self.snap_enabled and enabled else 0
        for item in items:
            item.moveBy(dx, dy)
        if sx:
            self.guides.append(("x", sx[1]))
        if sy:
            self.guides.append(("y", sy[1]))
        self.keep_group_on_page()
        self.viewport().update()

    def select_ids(self, ids):
        selected = set(ids)
        self.scene_model.blockSignals(True)
        for item in self.element_items:
            item.setSelected(item.element.id in selected)
        self.scene_model.blockSignals(False)
        self._selected()

    def mouseMoveEvent(self, event):
        if self.measuring:
            self.measure_end = self.mapToScene(event.position().toPoint())
            self.report_measurement()
            event.accept()
            return
        super().mouseMoveEvent(event)
        point = self.mapToScene(event.position().toPoint())
        if 0 <= point.x() <= self.page_width and 0 <= point.y() <= self.page_height:
            self.pointerMoved.emit(point.x(), point.y())

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        painter.save()
        painter.setClipRect(QRectF(0, 0, self.page_width, self.page_height))
        if self.grid_visible and not self.mode_preview:
            grid_color = QColor(get_colors()["primary"])
            grid_color.setAlpha(55)
            pen = QPen(grid_color, 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            for x in range(0, int(self.page_width)+1, 5):
                painter.drawLine(QLineF(x, 0, x, self.page_height))
            for y in range(0, int(self.page_height)+1, 5):
                painter.drawLine(QLineF(0, y, self.page_width, y))
        pen = QPen(QColor(get_colors()["primary"]), 1, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        for axis, value in ([] if self.mode_preview else self.guides):
            painter.drawLine(QLineF(value, 0, value, self.page_height) if axis == "x" else QLineF(0, value, self.page_width, value))
        if self.measure_start is not None and self.measure_end is not None:
            painter.drawLine(QLineF(self.measure_start, self.measure_end))
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
                if name == "copy" or (self.editable and not self.mode_preview):
                    self.command.emit(name)
                return
        if self.editable and not self.mode_preview and event.modifiers() & Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_D:
            self.command.emit("duplicate")
            return
        moves = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
                 Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if key in moves and not self.mode_preview and self.editable:
            if hasattr(self, "before_edit") and not self.before_edit():
                return
            before = self.snapshot()
            dx, dy = moves[key]
            step = 5 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0.5
            selected = [item for item in self.element_items if item.isSelected()]
            for item in selected:
                item.moveBy(dx*step, dy*step)
            self.keep_group_on_page()
            for item in selected:
                item.element.x_mm, item.element.y_mm = item.pos().x(), item.pos().y()
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
        if self.editable and not self.mode_preview and event.mimeData().hasFormat("application/x-pdc-field"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat("application/x-pdc-field") and not self.mode_preview and self.editable:
            point = self.mapToScene(event.position().toPoint())
            self.fieldDropped.emit(bytes(event.mimeData().data("application/x-pdc-field")).decode("utf-8"),
                                   max(0, point.x()), max(0, point.y()))
            event.acceptProposedAction()
