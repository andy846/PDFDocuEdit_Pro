"""Compact Designer chrome, scoped styles and full-message access."""
from __future__ import annotations

import html

from PyQt6.QtCore import QEvent, QSize, Qt
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QApplication, QLabel, QMenu, QMessageBox, QStatusBar, QWidget


class DesignerStatusBar(QStatusBar):
    """Reserve a readable row when embedded under the application stylesheet.

    Qt's styled status-bar size hint can collapse to its one-pixel border when
    min-height is zero, even though it contains visible labels. Calculate the
    content height independently so the main-window layout cannot clip them.
    """

    def _content_height(self):
        return max([
            self.fontMetrics().height() + 6,
            *(max(widget.sizeHint().height(), widget.minimumSizeHint().height()) + 4
              for widget in self.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly)
              if not widget.isHidden()),
        ])

    def sizeHint(self):
        size = super().sizeHint()
        size.setHeight(max(size.height(), self._content_height()))
        return size

    def minimumSizeHint(self):
        # Long messages should elide horizontally, rather than widening the app.
        return QSize(0, self._content_height())

    def event(self, event):
        result = super().event(event)
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange,
                            QEvent.Type.Polish, QEvent.Type.LayoutRequest, QEvent.Type.Show):
            # QMainWindow's native layout uses the styled status-bar item size,
            # which may bypass the Python sizeHint override. Reserve the row
            # explicitly, including after a theme/DPI change repolishes styles.
            height = self._content_height()
            if self.minimumHeight() != height:
                self.setMinimumHeight(height)
        return result


class CompactMessage(QLabel):
    """Keep the complete message API; paint a single elided line."""
    def __init__(self, parent=None):
        super().__init__("", parent)
        self.setAccessibleName("Designer status message")
        self.setMinimumWidth(0)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def setText(self, value):
        super().setText(value)
        self.setToolTip("<qt>" + html.escape(value).replace("\n", "<br>") + "</qt>")

    def sizeHint(self):
        return QSize(180, self.fontMetrics().height())

    def minimumSizeHint(self):
        return QSize(0, self.fontMetrics().height())

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        value = self.fontMetrics().elidedText(self.text().replace("\n", " "),
                                              Qt.TextElideMode.ElideRight, self.contentsRect().width())
        painter.drawText(self.contentsRect(), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, value)

    def details(self):
        if self.text():
            box = QMessageBox(self.window())
            box.setWindowTitle("Designer message")
            box.setTextFormat(Qt.TextFormat.PlainText)
            box.setText(self.text())
            box.exec()

    def mouseDoubleClickEvent(self, event):
        self.details()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.details()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _menu(self, point):
        menu = QMenu(self)
        menu.addAction("Show full message", self.details)
        menu.addAction("Copy full message", lambda: QApplication.clipboard().setText(self.text()))
        menu.exec(self.mapToGlobal(point))


def configure_compact_chrome(window):
    toolbar = window.project_toolbar
    toolbar.setObjectName("designerMainToolbar")
    toolbar.setIconSize(QSize(18, 18))
    toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    window.barcode_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    window.barcode_button.setToolTip("Insert Code 128, I25 or QR code")
    window.barcode_button.setAccessibleName("Insert barcode")
    import_button = toolbar.widgetForAction(window.actions["import"])
    import_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    window.actions["import"].setIconText("Data")
    window.tabs.setObjectName("designerModeTabs")
    controls = window.document_controls
    controls.setObjectName("designerDocumentControls")
    from PyQt6.QtWidgets import QSizePolicy
    controls.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    controls.setStyleSheet("""
        QWidget#designerDocumentControls QPushButton,
        QWidget#designerDocumentControls QToolButton { padding: 3px 5px; min-height: 0px; min-width: 0px; }
        QWidget#designerDocumentControls QComboBox,
        QWidget#designerDocumentControls QSpinBox { padding: 2px 4px; min-height: 0px; }
    """)
    window.document_control_row.setSpacing(4)
    window.preview_state.setWordWrap(False)
    window.preview_state.setMinimumWidth(0)
    window.preview_state.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    from ui.icons import icon
    window.preview_retry.setText("")
    window.preview_retry.setIcon(icon("rotate-cw"))
    window.preview_retry.setIconSize(QSize(16, 16))
    window.preview_retry.setAccessibleName("Refresh page preview")
    window.preview_retry.setMaximumWidth(28)
    window.preview_review.setText("Review")
    for button in (window.first, window.previous, window.next, window.last):
        button.setMaximumWidth(26)
        button.setToolTip(button.accessibleName())
    window.record.setMaximumWidth(140)
    window.record_navigation.layout().setContentsMargins(0, 0, 0, 0)
    window.record_navigation.layout().setSpacing(2)
    window.description.hide()
    status = window.statusBar()
    status.setObjectName("designerStatusBar")
    status.setSizeGripEnabled(False)
    status.setStyleSheet("""
        QStatusBar#designerStatusBar { padding: 0px; min-height: 0px; }
        QStatusBar#designerStatusBar::item { border: none; }
        QStatusBar#designerStatusBar QLabel { padding: 0px 2px; min-height: 0px; }
        QStatusBar#designerStatusBar QPushButton { padding: 2px 6px; min-height: 0px; }
        QStatusBar#designerStatusBar QProgressBar { min-height: 0px; max-height: 16px; }
    """)
    status.addWidget(window.message, 1)
    window.progress.setMaximumWidth(105)
    window.cancel_button.setText("Cancel")
    status.addPermanentWidget(window.progress)
    status.addPermanentWidget(window.cancel_button)
    # Keep full values in tooltips, use short visible metadata.
    window.page_status.setMinimumWidth(0)
    window.record_navigation.setVisible(window.tabs.currentIndex() == 2)
