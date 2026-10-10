"""Widget host for production controls shared by dialogs and workspace tabs."""
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget


class ProductionPanel(QWidget):
    finished = pyqtSignal(int)
    taskStarted = pyqtSignal(dict)
    taskResult = pyqtSignal(dict, dict)
    taskFailed = pyqtSignal(dict, str)
    taskEnded = pyqtSignal()
    controlsChanged = pyqtSignal()
    progressChanged = pyqtSignal(int, int, str)

    def __init__(self, title, geometry_key, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)

    def setModal(self, modal):
        # A QWidget remains embedded; the standalone host supplies modality.
        pass

    def accept(self):
        self.finished.emit(1)

    def reject(self):
        self.hide()
        self.finished.emit(0)
