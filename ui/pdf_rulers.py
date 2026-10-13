"""Paper-coordinate rulers for the PDF viewport; never render or modify a PDF."""
from __future__ import annotations

import math
from dataclasses import dataclass

from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, QSizeF, Qt, QTimer
from PyQt6.QtGui import QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import QInputDialog, QLabel, QMenu, QWidget

MM_PER_POINT = 25.4 / 72


@dataclass(frozen=True)
class ReferenceGuide:
    """Unrotated PDF points keep a guide attached to the same paper position."""
    identifier: int
    points: tuple[tuple[float, float], tuple[float, float]]


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
        self.setToolTip("Drag onto a page to add a guide. Right-click for guides and snapping settings.\n"
                        "PDF paper size; calibrated measurement distances are shown separately.")
        self.setCursor(Qt.CursorShape.SplitVCursor if horizontal else Qt.CursorShape.SplitHCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.installEventFilter(controller)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.controller.show_menu(event.globalPosition().toPoint())
        elif event.button() == Qt.MouseButton.LeftButton:
            self.controller.begin_guide(self, "y" if self.horizontal else "x")
        event.accept()

    def mouseMoveEvent(self, event):
        if self.controller.guide_drag is not None:
            self.controller.move_guide(event.globalPosition())
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.controller.finish_guide(event.globalPosition())
        event.accept()

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
        self.guides: dict[int, list[ReferenceGuide]] = {}
        self._guide_page_ids = {}
        self.guides_visible = True
        self.snap_enabled = True
        self.guide_drag = None
        self._guide_serial = 0
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
        self.corner.setCursor(Qt.CursorShape.PointingHandCursor)
        self.corner.installEventFilter(self)
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
        overlay._measure_snapper = self.snap_point
        self.sync_guides(overlay)

    def sync_guides(self, overlay=None):
        overlays = [overlay] if overlay is not None else [v.overlay for v in self.canvas._page_views.values()]
        for item in overlays:
            page = item._page_num
            if self.guides.get(page) and self.canvas._doc is not None and (
                    page >= self.canvas._doc.page_count
                    or self.canvas._doc.page_xref(page) != self._guide_page_ids.get(page)):
                # Reordered/replaced pages must not inherit another page's guides.
                self.guides.pop(page, None)
                self._guide_page_ids.pop(page, None)
            points = tuple(g.points for g in self.guides.get(item._page_num, ())) if (
                self.enabled and self.guides_visible) else ()
            if item._reference_guides != points:
                item._reference_guides = points
                item.update()

    def clear_guides(self, page=None):
        self.cancel_guide()
        if page is None:
            self.guides.clear()
            self._guide_page_ids.clear()
        else:
            self.guides.pop(page, None)
            self._guide_page_ids.pop(page, None)
        self.sync_guides()

    def snap_point(self, overlay, position, modifiers, fixed_axis=None):
        if (not self.enabled or not self.snap_enabled
                or modifiers & Qt.KeyboardModifier.AltModifier):
            return position
        result = QPointF(position)
        targets = {"x": [0, overlay._page_rect.width/overlay._scale],
                   "y": [0, overlay._page_rect.height/overlay._scale]}
        if self.guides_visible:
            for guide in self.guides.get(overlay._page_num, ()):
                first, last = (overlay.pdf_point_to_widget(p) for p in guide.points)
                axis = "x" if abs(first.x()-last.x()) < .01 else "y"
                targets[axis].append(first.x() if axis == "x" else first.y())
        for axis, candidates in targets.items():
            if axis == fixed_axis:
                continue
            coordinate = result.x() if axis == "x" else result.y()
            nearest = min(candidates, key=lambda value: abs(value-coordinate))
            if abs(nearest-coordinate) <= 8:
                result.setX(nearest) if axis == "x" else result.setY(nearest)
        return result

    def _overlay(self, page):
        view = self.canvas._page_views.get(page)
        return view.overlay if view is not None and view.parentWidget() is self.canvas._pager else None

    def add_guide(self, page, axis, mm, identifier=None):
        overlay = self._overlay(page)
        if overlay is None or axis not in {"x", "y"} or not math.isfinite(mm):
            return None
        extent = overlay._page_rect.width if axis == "x" else overlay._page_rect.height
        if not 0 <= mm <= extent*MM_PER_POINT:
            return None
        value = mm/MM_PER_POINT/overlay._scale
        width, height = overlay._page_rect.width/overlay._scale, overlay._page_rect.height/overlay._scale
        pair = (QPointF(value, 0), QPointF(value, height)) if axis == "x" else (
            QPointF(0, value), QPointF(width, value))
        points = tuple(tuple(overlay.widget_to_pdf(p)) for p in pair)
        if identifier is None:
            self._guide_serial += 1
            identifier = self._guide_serial
        guide = ReferenceGuide(identifier, points)
        self._guide_page_ids[page] = self.canvas._doc.page_xref(page)
        items = self.guides.setdefault(page, [])
        items[:] = [g for g in items if g.identifier != identifier]
        items.append(guide)
        self.sync_guides(overlay)
        return guide

    def _guide_hit(self, overlay, position):
        for guide in reversed(self.guides.get(overlay._page_num, ())):
            first, last = (overlay.pdf_point_to_widget(p) for p in guide.points)
            axis = "x" if abs(first.x()-last.x()) < .01 else "y"
            coordinate = first.x() if axis == "x" else first.y()
            if abs((position.x() if axis == "x" else position.y())-coordinate) <= 5:
                return guide, axis, coordinate
        return None

    def begin_guide(self, owner, axis, page=None, original=None, offset=0):
        self.cancel_guide()
        page = self.reference_page if page is None else page
        if page is None or self._overlay(page) is None:
            return
        self.guides_visible = True
        self.guide_drag = {"owner": owner, "page": page, "axis": axis,
                           "original": original, "current": original, "offset": offset}
        owner.setFocus(Qt.FocusReason.MouseFocusReason)
        owner.grabMouse()
        self.sync_guides()

    def move_guide(self, global_position):
        drag = self.guide_drag
        if drag is None:
            return
        if drag["original"] is None:
            # New guides belong to the page they are dropped on, including facing pages.
            for page in self.canvas._page_views:
                candidate = self._overlay(page)
                if candidate is None:
                    continue
                point = QPointF(candidate.mapFromGlobal(global_position.toPoint()))
                if QRectF(0, 0, candidate._page_rect.width/candidate._scale,
                          candidate._page_rect.height/candidate._scale).contains(point):
                    if page != drag["page"]:
                        if drag["current"] is not None:
                            self._remove_guide(drag["page"], drag["current"].identifier)
                        drag["page"], drag["current"] = page, None
                        self.sync_guides()
                    break
        overlay = self._overlay(drag["page"])
        if overlay is None:
            self.cancel_guide()
            return
        position = QPointF(overlay.mapFromGlobal(global_position.toPoint()))
        coordinate = (position.x() if drag["axis"] == "x" else position.y())-drag["offset"]
        extent = overlay._page_rect.width if drag["axis"] == "x" else overlay._page_rect.height
        value = max(0, min(coordinate*overlay._scale*MM_PER_POINT, extent*MM_PER_POINT))
        current = drag["current"]
        drag["current"] = self.add_guide(drag["page"], drag["axis"], value,
                                         current.identifier if current is not None else None)

    def finish_guide(self, global_position):
        drag = self.guide_drag
        if drag is None:
            return
        self.move_guide(global_position)
        # A mode change or document close can retire the source page.
        if self.guide_drag is None:
            return
        overlay = self._overlay(drag["page"])
        inside = overlay is not None and QRectF(0, 0, overlay._page_rect.width/overlay._scale,
                     overlay._page_rect.height/overlay._scale).contains(
                         QPointF(overlay.mapFromGlobal(global_position.toPoint())))
        if not inside and drag["current"] is not None:
            self._remove_guide(drag["page"], drag["current"].identifier)
        self.guide_drag = None
        drag["owner"].releaseMouse()
        self.sync_guides()

    def _remove_guide(self, page, identifier):
        self.guides[page] = [g for g in self.guides.get(page, ()) if g.identifier != identifier]

    def cancel_guide(self):
        drag = self.guide_drag
        if drag is None:
            return
        self.guide_drag = None
        if drag["current"] is not None:
            self._remove_guide(drag["page"], drag["current"].identifier)
        if drag["original"] is not None:
            self.guides.setdefault(drag["page"], []).append(drag["original"])
        drag["owner"].releaseMouse()
        self.sync_guides()

    def edit_position(self, page, axis, guide=None):
        overlay = self._overlay(page)
        if overlay is None:
            return
        unit = self.canvas.measure_unit
        factor = 10 if unit == "cm" else 1
        extent = (overlay._page_rect.width if axis == "x" else overlay._page_rect.height)*MM_PER_POINT/factor
        initial = extent/2
        if guide is not None:
            point = overlay.pdf_point_to_widget(guide.points[0])
            initial = (point.x() if axis == "x" else point.y())*overlay._scale*MM_PER_POINT/factor
        value, accepted = QInputDialog.getDouble(self.canvas, "Reference guide",
            f"Page {page+1} · {'X from left' if axis == 'x' else 'Y from top'} ({unit}, paper size):",
            initial, 0, extent, 3)
        if accepted:
            self.guides_visible = True
            self.add_guide(page, axis, value*factor, guide.identifier if guide else None)

    def show_menu(self, global_position, page=None, hit=None):
        page = self.reference_page if page is None else page
        menu = QMenu(self.canvas)
        if hit is not None:
            guide, axis, _ = hit
            menu.addAction("Set guide position…", lambda: self.edit_position(page, axis, guide))
            menu.addAction("Remove guide", lambda: (self._remove_guide(page, guide.identifier), self.sync_guides()))
            menu.addSeparator()
        visible = menu.addAction("Show reference guides")
        visible.setCheckable(True)
        visible.setChecked(self.guides_visible)
        visible.toggled.connect(self.set_guides_visible)
        snap = menu.addAction("Snap measurements to guides and page edges")
        snap.setCheckable(True)
        snap.setChecked(self.snap_enabled)
        snap.toggled.connect(lambda enabled: setattr(self, "snap_enabled", enabled))
        menu.addSeparator()
        for axis, title in (("y", "Add horizontal guide…"), ("x", "Add vertical guide…")):
            action = menu.addAction(title, lambda checked=False, a=axis: self.edit_position(page, a))
            action.setEnabled(page is not None and self._overlay(page) is not None)
        clear = menu.addAction("Clear guides on this page", lambda: self.clear_guides(page))
        clear.setEnabled(page is not None and bool(self.guides.get(page)))
        try:
            menu.exec(global_position)
        finally:
            menu.deleteLater()

    def set_guides_visible(self, visible):
        self.cancel_guide()
        self.guides_visible = visible
        self.sync_guides()

    def reset_pointer(self, *_):
        self.pointer_timer.stop()
        self._pending_pointer = None
        self.pointer = None
        self.refresh()

    def flush_pointer(self):
        if not getattr(self, "enabled", False):
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
        self.cancel_guide()
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
        self.sync_guides()

    def refresh(self, *_):
        if not getattr(self, "enabled", False):
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
                               "Click for reference guides and snapping settings.\n"
                               "Drag from rulers to add guides; Alt+drag to move; right-click to edit.\n"
                               "Alt disables measurement snapping. Guides are not saved in the PDF.")
        self.horizontal.update()
        self.vertical.update()

    def eventFilter(self, obj, event):
        # Qt can dispatch child/widget events during native construction or
        # teardown while this Python wrapper's attributes are not available.
        # An exception escaping an event filter causes PyQt to abort the app.
        if getattr(self, "enabled", False):
            kind = event.type()
            if (self.guide_drag is not None and kind in {QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress}
                    and event.key() == Qt.Key.Key_Escape):
                if kind == QEvent.Type.KeyPress:
                    self.cancel_guide()
                event.accept()
                return True
            if obj is self.corner and kind == QEvent.Type.MouseButtonPress:
                self.show_menu(event.globalPosition().toPoint())
                return True
            if hasattr(obj, "_reference_guides"):
                if self.guide_drag is not None and obj is self.guide_drag["owner"]:
                    if kind == QEvent.Type.MouseMove:
                        self.move_guide(event.globalPosition())
                        return True
                    if kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                        self.finish_guide(event.globalPosition())
                        return True
                if (self.guides_visible and obj._measure_origin is None and obj._measure_drag is None
                        and kind == QEvent.Type.MouseButtonPress):
                    hit = self._guide_hit(obj, event.position())
                    # Keep normal clicks on guides available for measuring.
                    if hit is not None and event.button() == Qt.MouseButton.LeftButton and (
                            event.modifiers() & Qt.KeyboardModifier.AltModifier):
                        guide, axis, coordinate = hit
                        offset = (event.position().x() if axis == "x" else event.position().y())-coordinate
                        self.begin_guide(obj, axis, obj._page_num, guide, offset)
                        return True
                    if hit is not None and event.button() == Qt.MouseButton.RightButton:
                        self.show_menu(event.globalPosition().toPoint(), obj._page_num, hit)
                        return True
            if event.type() == QEvent.Type.MouseMove:
                self._pending_pointer = obj.mapTo(self.canvas.viewport(), event.position().toPoint())
                if not self.pointer_timer.isActive():
                    self.pointer_timer.start()
            elif event.type() == QEvent.Type.Leave:
                self.reset_pointer()
            elif event.type() == QEvent.Type.Resize:
                self.refresh()
        return False
