"""Compact, cancellable background-work status bar."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton

from styles.tokens import S


class TaskBar(QFrame):
    cancelRequested = pyqtSignal()
    activityChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("taskBar")
        self.setAccessibleName("Background work")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(S.MD, S.XS, S.MD, S.XS)
        layout.setSpacing(S.SM)
        self._label = QLabel("Working…")
        self._label.setMinimumWidth(160)
        layout.addWidget(self._label)
        self._detail = QLabel("")
        self._detail.setObjectName("secondary")
        layout.addWidget(self._detail, 1)
        self._progress = QProgressBar()
        self._progress.setObjectName("taskProgress")
        self._progress.setTextVisible(False)
        self._progress.setFixedWidth(160)
        layout.addWidget(self._progress)
        self._cancel = QPushButton("Cancel")
        self._cancel.setAccessibleName("Cancel background work")
        self._cancel.clicked.connect(self.cancelRequested.emit)
        layout.addWidget(self._cancel)
        self._owner = None
        self.active = False
        self.hide()

    def start(self, label: str, cancellable: bool = True, *, owner=None) -> None:
        self._owner = owner
        was_active = self.active
        self.active = True
        self._label.setText(label)
        self._detail.clear()
        self._progress.setRange(0, 0)
        self._cancel.setText("Cancel")
        self._cancel.setVisible(cancellable)
        self._cancel.setEnabled(cancellable)
        self.show()
        if not was_active:
            self.activityChanged.emit(True)

    def update_progress(self, current: int, total: int, detail: str) -> None:
        self._detail.setText(detail)
        if total > 0:
            self._progress.setRange(0, total)
            self._progress.setValue(min(current, total))
        else:
            self._progress.setRange(0, 0)

    def set_cancelling(self) -> None:
        self._detail.setText("Waiting for the current safe checkpoint…")
        self._cancel.setText("Cancelling…")
        self._cancel.setEnabled(False)

    def owns(self, owner) -> bool:
        return self.active and self._owner is owner

    def clear(self, *, owner=None) -> bool:
        if owner is not None and not self.owns(owner):
            return False
        was_active = self.active
        self.active = False
        self._owner = None
        if was_active:
            self.activityChanged.emit(False)
        self.hide()
        self._detail.clear()
        self._cancel.setEnabled(True)
        self._cancel.show()
        return was_active
