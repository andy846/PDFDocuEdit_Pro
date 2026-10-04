"""Source-page search-region selection with exact millimetre coordinates."""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPen, QPixmap, QTransform
from PyQt6.QtWidgets import QGraphicsScene, QGraphicsView

from composition.template.model import MM_TO_PT


class RegionView(QGraphicsView):
    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.setScene(QGraphicsScene(self))
        self.setMinimumHeight(140)
        self.setBackgroundBrush(QColor("#59616b"))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.anchor = self.region_item = None
        self.fit_mode = True
        self.loading = False
        self.setToolTip("Drag inside the page to select a region. Ctrl+wheel zooms; hold Space to pan. Coordinates are millimetres from the visible top-left.")

    def load(self, path, geometry):
        pixmap = QPixmap(path)
        if pixmap.isNull():
            raise ValueError("Source preview could not be loaded. Select the page again.")
        self.anchor = self.region_item = None
        self.loading = False
        self.scene().clear()
        width, height = geometry["width_pt"]/MM_TO_PT, geometry["height_pt"]/MM_TO_PT
        item = self.scene().addPixmap(pixmap)
        item.setTransform(QTransform.fromScale(width/pixmap.width(), height/pixmap.height()))
        self.scene().setSceneRect(0, 0, width, height)
        self.update_region()
        if self.fit_mode:
            self.fit_page()

    def fit_page(self):
        self.fit_mode = True
        if not self.sceneRect().isEmpty():
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def update_region(self, *args):
        if self.anchor is not None or self.sceneRect().isEmpty():
            return
        rect = QRectF(*[control.value() for control in self.dialog.region]).intersected(self.sceneRect())
        if self.region_item is None:
            pen = QPen(QColor("#d42b91"), 1)
            pen.setCosmetic(True)
            self.region_item = self.scene().addRect(rect, pen)
            self.region_item.setZValue(1)
        self.region_item.setRect(rect)
        self.region_item.setVisible(not self.dialog.whole.isChecked() and not rect.isEmpty())

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.2 if event.angleDelta().y() > 0 else 1/1.2
            if .1 <= self.transform().m11()*factor <= 40:
                self.fit_mode = False
                self.scale(factor, factor)
            event.accept()
        else:
            super().wheelEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit_mode:
            self.fit_page()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            event.accept()
        else:
            super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.anchor = None
        super().focusOutEvent(event)
        self.update_region()

    def mousePressEvent(self, event):
        if self.dialog.method.currentData() == "smart" and not self.dialog.teaching:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        if self.dragMode() == QGraphicsView.DragMode.ScrollHandDrag:
            return super().mousePressEvent(event)
        if self.loading:
            event.accept()
            return
        point = self.mapToScene(event.pos())
        if event.button() == Qt.MouseButton.LeftButton and self.sceneRect().contains(point):
            self.anchor = point
            if self.region_item:
                self.scene().removeItem(self.region_item)
            pen = QPen(QColor("#d42b91"), 1)
            pen.setCosmetic(True)
            self.region_item = self.scene().addRect(QRectF(point, point), pen)
            self.region_item.setZValue(1)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.anchor is not None:
            rect = QRectF(self.anchor, self.mapToScene(event.pos())).normalized().intersected(self.sceneRect())
            self.region_item.setRect(rect)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.anchor is not None:
            rect = QRectF(self.anchor, self.mapToScene(event.pos())).normalized().intersected(self.sceneRect())
            self.anchor = None
            if rect.width() > .1 and rect.height() > .1:
                self.dialog.whole.setChecked(False)
                for control, value in zip(self.dialog.region, (rect.x(), rect.y(), rect.width(), rect.height()), strict=True):
                    control.blockSignals(True)
                    control.setValue(value)
                    control.blockSignals(False)
                self.dialog.invalidate()
            self.update_region()
            event.accept()
        else:
            super().mouseReleaseEvent(event)
