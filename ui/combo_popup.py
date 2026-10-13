"""Readable combo popups even when their containing inspector is narrow."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox


class WideComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(10)
        self.setMaxVisibleItems(12)
        self.view().setTextElideMode(Qt.TextElideMode.ElideNone)
        self.view().setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.currentTextChanged.connect(self.setToolTip)

    def showPopup(self):
        metrics = self.fontMetrics()
        desired = max([self.width(), *(metrics.horizontalAdvance(self.itemText(i))+48 for i in range(self.count()))])
        available = self.screen().availableGeometry().width()-24
        width = min(max(80, available), desired)
        self.view().setMinimumWidth(width)
        self.view().setMaximumWidth(max(80, available))
        super().showPopup()
