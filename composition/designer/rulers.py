"""Viewport rulers with millimetre ticks following canvas pan and zoom."""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget

from styles.theme import get_colors


class Ruler(QWidget):
    def __init__(self, canvas, horizontal):
        super().__init__(canvas)
        self.canvas, self.horizontal = canvas, horizontal
        self.setAccessibleName("Horizontal millimetre ruler" if horizontal else "Vertical millimetre ruler")

    def paintEvent(self, event):
        painter = QPainter(self)
        colors = get_colors()
        painter.fillRect(self.rect(), QColor(colors["bg_sidebar"]))
        painter.setPen(QColor(colors["text_secondary"]))
        font = painter.font()
        font.setPixelSize(10)
        painter.setFont(font)
        scale = max(.001, self.canvas.transform().m11())
        step = next((n for n in (1, 2, 5, 10, 20, 50, 100) if n*scale >= 4), 100)
        major = step*5
        length = self.canvas.page_width if self.horizontal else self.canvas.page_height
        visible = self.width() if self.horizontal else self.height()
        first = self.canvas.mapToScene(0, 0)
        start = max(0, math.floor((first.x() if self.horizontal else first.y())/step)*step)
        for value in range(int(start), int(length)+1, step):
            point = self.canvas.mapFromScene(QPointF(value, 0) if self.horizontal else QPointF(0, value))
            pos = point.x() if self.horizontal else point.y()
            if pos > visible+20:
                break
            if pos < -20:
                continue
            tick = 9 if value % major == 0 else 4
            if self.horizontal:
                painter.drawLine(pos, self.height()-1, pos, self.height()-tick)
                if value % major == 0:
                    painter.drawText(pos+2, 11, str(value))
            else:
                painter.drawLine(self.width()-1, pos, self.width()-tick, pos)
                if value % major == 0:
                    painter.save()
                    painter.translate(11, pos+2)
                    painter.rotate(-90)
                    painter.drawText(0, 0, str(value))
                    painter.restore()
        painter.end()
