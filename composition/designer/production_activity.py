"""Persistent production activity, separate from menu tips and the result report."""
from __future__ import annotations

from time import monotonic

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QGridLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget


def duration(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds//60:02d}:{seconds%60:02d}"


class ProductionActivity(QWidget):
    def __init__(self, cancel, parent=None):
        super().__init__(parent)
        self.setAccessibleName("Live production progress")
        self.running = self.cancelling = False
        self.started = self.updated = 0
        self.stage = ""
        self.cancel = cancel
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(3)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        self.label.setMinimumWidth(0)
        self.header = QGridLayout()
        self.header.setContentsMargins(0, 0, 0, 0)
        self.header.setHorizontalSpacing(12)
        layout.addLayout(self.header)
        self.detail = QLabel()
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setWordWrap(True)
        self.detail.setMinimumWidth(0)
        self.detail.setObjectName("secondary")
        self.cancel_button = QPushButton("Cancel job")
        self.cancel_button.clicked.connect(self.request_cancel)
        self._compact = None
        self._arrange_header()
        self.bar = QProgressBar()
        self.bar.setMaximumHeight(16)
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 0)
        layout.addWidget(self.bar)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.hide()

    def set_running(self, running):
        running = bool(running)
        if running == self.running:
            return
        self.running = running
        self.setVisible(running)
        if running:
            self.started = self.updated = monotonic()
            self.cancelling = False
            self.stage = "Starting reviewed production…"
            self.cancel_button.setEnabled(True)
            self.bar.setRange(0, 0)
            self.timer.start()
            self.refresh()
        else:
            self.timer.stop()

    def update_progress(self, done, total, message):
        if not self.running or self.cancelling:
            return
        self.stage = message
        self.updated = monotonic()
        self.bar.setRange(0, max(0, total))
        self.bar.setValue(max(0, done))
        self.refresh()

    def refresh(self):
        if not self.running:
            return
        now = monotonic()
        self.label.setText("Cancelling · waiting for safe cleanup…" if self.cancelling else self.stage)
        text = f"Job elapsed {duration(now-self.started)}"
        if now-self.updated >= 30 and not self.cancelling:
            text += f" · No progress update for {duration(now-self.updated)}; waiting for the worker. Cancel is available."
        self.detail.setText(text)

    def cancel_pending(self):
        if self.running:
            self.cancelling = True
            self.cancel_button.setEnabled(False)
            self.refresh()

    def request_cancel(self):
        self.cancel_pending()
        self.cancel()

    def _arrange_header(self):
        compact = self.width() < 800
        if compact == self._compact:
            return
        self._compact = compact
        for widget in (self.label, self.detail, self.cancel_button):
            self.header.removeWidget(widget)
        self.header.setColumnStretch(0, 1)
        if compact:
            self.header.addWidget(self.label, 0, 0, 1, 3)
            self.header.addWidget(self.detail, 1, 0, 1, 2)
            self.header.addWidget(self.cancel_button, 1, 2)
        else:
            self.header.addWidget(self.label, 0, 0)
            self.header.addWidget(self.detail, 0, 1)
            self.header.addWidget(self.cancel_button, 0, 2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange_header()
