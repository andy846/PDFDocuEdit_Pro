"""A mode-independent shutdown notice; ordinary work has no extra chrome."""
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class CloseStatusBar(QFrame):
    retryRequested = pyqtSignal()
    returnRequested = pyqtSignal()
    diagnosticsRequested = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("closeStatusBar")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAccessibleName("Safe shutdown status")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        row = QHBoxLayout()
        row.addStretch()
        self.retry_button = QPushButton("Retry close")
        self.return_button = QPushButton("Return to work")
        self.diagnostics_button = QPushButton("Diagnostics…")
        for button, signal in ((self.retry_button, self.retryRequested),
                               (self.return_button, self.returnRequested),
                               (self.diagnostics_button, self.diagnosticsRequested)):
            button.clicked.connect(signal.emit)
            row.addWidget(button)
        layout.addLayout(row)
        self.hide()

    def update_status(self, status):
        if not status['visible']:
            self.hide()
            return
        failure = status['failed']
        if self.property('failed') != failure:
            self.setProperty('failed', failure)
            self.style().unpolish(self)
            self.style().polish(self)
        reasons = {
            'preferences': 'Could not save application preferences before closing.',
            'preparation': 'Close preparation could not finish.',
            'cleanup': 'Safe shutdown could not finish.',
            'detached_windows': 'Waiting for other PDF windows to close safely.',
            'pdf_tasks': 'Waiting for background PDF work to finish.',
            'pdf_readers': 'Waiting for PDF readers to release documents.',
            'workspace_readers': 'Waiting for workspace readers to release documents.',
            'comparison': 'Waiting for PDF comparison to stop.',
            'pdf_tools': 'Waiting for PDF production tools to stop.',
            'tool_workers': 'Waiting for tool jobs to stop.',
            'mutation': 'Waiting for the current document edit to finish.',
            'printing_or_update': 'Finish printing or the update download before closing.',
        }
        message = reasons.get(status['reason'], 'Waiting for safe shutdown.')
        if failure:
            message += (' You can retry or return to work.' if status['can_return'] else
                        ' Cleanup has started; editing cannot resume. Retry close or view diagnostics.')
        else:
            message += ' The window will close automatically when safe.'
        self.message.setText(f"{message}\n{status['elapsed']}s elapsed · "
                             f"{status['tasks']} background job(s) · {status['readers']} pending reader(s)")
        self.retry_button.setVisible(failure)
        self.return_button.setVisible(failure and status['can_return'])
        self.diagnostics_button.setVisible(not status['can_return'] or not failure)
        self.show()
