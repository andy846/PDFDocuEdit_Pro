"""Inspector scrolling keeps the whole control visible, including its border."""
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QScrollArea


class InspectorScrollArea(QScrollArea):
    def ensureWidgetVisible(self, widget, xMargin=50, yMargin=50):
        content = self.widget()
        if content is None or not content.isAncestorOf(widget):
            return super().ensureWidgetVisible(widget, xMargin, yMargin)
        # Qt's implementation can use an editor's focus proxy rectangle and
        # leave the outer text box partly clipped. Use the full widget bounds.
        point = widget.mapTo(content, QPoint())
        self.ensureVisible(point.x()+widget.width()//2, point.y()+widget.height()//2,
                           xMargin+(widget.width()+1)//2, yMargin+(widget.height()+1)//2)
