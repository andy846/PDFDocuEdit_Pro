"""Named Quick-only region presentation; extraction coordinates stay in mm."""
from __future__ import annotations

import copy

from PyQt6.QtCore import QPoint, QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QPen
from PyQt6.QtWidgets import QApplication, QGraphicsItem, QMenu

from styles.theme import get_color
from workflow.regions_ui import RegionCanvas


class ExtractionCanvas(RegionCanvas):
    def __init__(self, dialog):
        super().__init__(dialog)
        self.draw_start = None
        self.draft_item = None
        self.active_label = self.resize_handle = None

    def load(self, path, geometry):
        self.dialog.cancel_add()
        self.move_start = None
        self.dialog.before_drag = None
        super().load(path, geometry)

    def cancel_draft(self):
        self.draw_start = None
        for item in list(self.scene().items()):
            if item.data(0) == "quick_draft":
                self.scene().removeItem(item)
        self.draft_item = None

    def update_region(self, *_):
        self.render_regions()

    def fit_page(self, *args):
        super().fit_page(*args)
        self.render_regions()

    def place_label(self, badge, rect):
        start = self.mapFromScene(self.sceneRect().topLeft())
        end = self.mapFromScene(self.sceneRect().bottomRight())
        point = self.mapFromScene(rect.topLeft())
        x = max(start.x(), min(point.x(), round(end.x()-badge.rect().width())))
        y = max(start.y(), min(point.y(), round(end.y()-badge.rect().height())))
        badge.setPos(self.mapToScene(QPoint(x, y)))

    def render_regions(self):
        roots = [item for item in self.scene().items() if item.parentItem() is None
                 and str(item.data(0)).startswith("quick_") and item.data(0) != "quick_draft"]
        for item in roots:
            self.scene().removeItem(item)
        self.region_item = self.active_label = self.resize_handle = None
        if self.sceneRect().isEmpty():
            return
        dialog = self.dialog
        for index, region in enumerate(dialog.regions):
            active = index == dialog.current
            if not dialog.show_all_regions and not active:
                continue
            rect = QRectF(region["x_mm"], region["y_mm"], region["width_mm"], region["height_mm"])
            color = QColor(get_color("primary") if active else get_color("text_secondary"))
            pen = QPen(color, 2.5 if active else 1)
            pen.setCosmetic(True)
            if not active:
                pen.setStyle(Qt.PenStyle.DashLine)
            box = self.scene().addRect(rect, pen)
            box.setData(0, "quick_region")
            box.setData(1, index)
            box.setZValue(3 if active else 1)
            if not active:
                box.setOpacity(.55)
            full_name = f"{index+1:02d} · {region['name']}"
            metrics = QFontMetrics(QApplication.font())
            label_text = metrics.elidedText(full_name, Qt.TextElideMode.ElideRight, 160)
            badge = self.scene().addRect(QRectF(0, 0, metrics.horizontalAdvance(label_text)+10, metrics.height()+4),
                                          QPen(color), QColor(get_color("primary") if active else get_color("bg_elevated")))
            badge.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            badge.setData(0, "quick_label")
            badge.setData(1, index)
            badge.setToolTip(full_name)
            self.place_label(badge, rect)
            badge.setZValue(6 if active else 4)
            text = self.scene().addSimpleText(label_text, QApplication.font())
            text.setParentItem(badge)
            text.setPos(5, 2)
            text.setBrush(QColor(get_color("on_primary") if active else get_color("text_primary")))
            text.setData(0, "quick_label_text")
            text.setData(1, index)
            text.setToolTip(full_name)
            if active:
                self.region_item, self.active_label = box, badge
                handle = self.scene().addRect(QRectF(-4, -4, 8, 8), QPen(color), color)
                handle.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                handle.setData(0, "quick_handle")
                handle.setData(1, index)
                handle.setPos(rect.bottomRight())
                handle.setZValue(8)
                self.resize_handle = handle

    def hits(self, point, *, visible_only=False):
        return [index for index, r in enumerate(self.dialog.regions)
                if (not visible_only or self.dialog.show_all_regions or index == self.dialog.current)
                and QRectF(r["x_mm"], r["y_mm"], r["width_mm"], r["height_mm"]).contains(point)]

    def overlap_menu(self, point):
        menu = QMenu(self)
        menu.setTitle("Select overlapping field")
        for index in self.hits(point):
            action = menu.addAction(f"{index+1:02d} · {self.dialog.regions[index]['name']}")
            action.setCheckable(True)
            action.setChecked(index == self.dialog.current)
            action.triggered.connect(lambda checked=False, row=index: self.dialog.list.setCurrentRow(row))
        return menu

    def contextMenuEvent(self, event):
        menu = self.overlap_menu(self.mapToScene(event.pos()))
        if menu.actions():
            menu.exec(event.globalPos())
        menu.deleteLater()

    def mousePressEvent(self, event):
        if self.dragMode() == self.DragMode.ScrollHandDrag:
            return super().mousePressEvent(event)
        if (self.loading or self.dialog.host.active or self.dialog.raster_page != self.dialog.page.value()
                or event.button() != Qt.MouseButton.LeftButton):
            event.accept()
            return
        point = self.mapToScene(event.pos())
        if self.dialog.draw_mode:
            if self.sceneRect().contains(point):
                self.draw_start = point
                pen = QPen(QColor(get_color("primary")), 2)
                pen.setCosmetic(True)
                self.draft_item = self.scene().addRect(QRectF(point, point), pen)
                self.draft_item.setData(0, "quick_draft")
            event.accept()
            return
        item = self.itemAt(event.pos())
        if item and item.data(0) in ("quick_label", "quick_label_text"):
            self.dialog.list.setCurrentRow(item.data(1))
            event.accept()
            return
        candidates = self.hits(point, visible_only=True)
        handle_hit = bool(item and item.data(0) == "quick_handle")
        if self.dialog.current not in candidates and not handle_hit:
            if len(candidates) == 1:
                self.dialog.list.setCurrentRow(candidates[0])
            elif len(candidates) > 1:
                self._menu = self.overlap_menu(point)
                self._menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
                self._menu.popup(event.globalPosition().toPoint())
                event.accept()
                return
            else:
                event.accept()
                return
        if self.region_item:
            rect = QRectF(self.region_item.rect())
            corner = self.mapFromScene(rect.bottomRight())
            resize = (corner-event.position().toPoint()).manhattanLength() <= 12
            self.move_start = (point, rect, resize)
            self.dialog.before_drag = copy.deepcopy(self.dialog.regions)
        event.accept()

    def mouseMoveEvent(self, event):
        if self.draw_start is not None:
            point = self.mapToScene(event.pos())
            self.draft_item.setRect(QRectF(self.draw_start, point).normalized().intersected(self.sceneRect()))
            event.accept()
        else:
            super().mouseMoveEvent(event)
            if self.move_start and self.region_item:
                if self.active_label:
                    self.place_label(self.active_label, self.region_item.rect())
                if self.resize_handle:
                    self.resize_handle.setPos(self.region_item.rect().bottomRight())

    def mouseReleaseEvent(self, event):
        if self.draw_start is not None:
            rect = QRectF(self.draft_item.rect())
            self.cancel_draft()
            if rect.width() > .1 and rect.height() > .1:
                self.dialog.finish_add(rect)
            event.accept()
        elif self.move_start:
            super().mouseReleaseEvent(event)
        else:
            event.accept()
