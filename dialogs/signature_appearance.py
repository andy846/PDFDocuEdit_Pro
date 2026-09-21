"""Handwritten image capture, with no digital-signature claims."""
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QDialogButtonBox, QLabel, QPushButton, QVBoxLayout

from ui.responsive import ResponsiveDialog


class SignaturePad(QLabel):
    def __init__(self):
        super().__init__()
        self.setFixedSize(620, 210)
        self.image = QPixmap(self.size())
        self.last = None
        self.clear_ink()

    def clear_ink(self):
        self.image.fill(Qt.GlobalColor.transparent)
        self.setPixmap(self.image)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.last = event.position().toPoint()

    def mouseMoveEvent(self, event):
        if self.last is not None and event.buttons() & Qt.MouseButton.LeftButton:
            point = event.position().toPoint()
            painter = QPainter(self.image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor("#16283c"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(self.last, point)
            painter.end()
            self.last = point
            self.setPixmap(self.image)

    def mouseReleaseEvent(self, event):
        self.last = None


class SignatureAppearanceDialog(ResponsiveDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Draw signature appearance")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Draw below. This creates a picture, not a digital signature."))
        self.pad = SignaturePad()
        self.pad.setStyleSheet("background: white; border: 1px solid #98a6b5")
        layout.addWidget(self.pad)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.pad.clear_ink)
        layout.addWidget(clear)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def image_bytes(self):
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        self.pad.image.save(buffer, "PNG")
        return bytes(data)
