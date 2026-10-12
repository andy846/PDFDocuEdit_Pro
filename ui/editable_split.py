"""Pair live PDF sessions without copying their engines or editing state."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QSplitter, QToolButton, QVBoxLayout


class EditableSplit(QFrame):
    def __init__(self, workspace, first, second):
        super().__init__(workspace)
        self.workspace = workspace
        self.sessions = (first, second)
        self.active = first
        self._syncing = False
        self.sync_page = False
        self.sync_zoom = False
        self._connections = []
        self.setObjectName("editablePdfSplit")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(QLabel("Split View · click either document to edit"), 1)
        for text, tip, callback in (
            ("⇄", "Swap documents", self.swap),
            ("▥ / ▤", "Switch between side by side and stacked", self.toggle_orientation),
            ("×", "Close split view; keep both documents open", workspace.end_pair),
        ):
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.clicked.connect(callback)
            header.addWidget(button)
        layout.addLayout(header)
        self.splitter = QSplitter(self)
        self.splitter.setOrientation(
            Qt.Orientation.Horizontal if first.split_orientation == "horizontal" else Qt.Orientation.Vertical
        )
        layout.addWidget(self.splitter, 1)
        self.frames = {}
        self.labels = {}
        for session in self.sessions:
            frame = QFrame()
            frame.setObjectName("editablePdfPane")
            pane = QVBoxLayout(frame)
            pane.setContentsMargins(2, 2, 2, 2)
            title = QToolButton()
            title.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            title.clicked.connect(lambda checked=False, s=session: self.activate(s))
            pane.addWidget(title)
            pane.addWidget(session.tab_widget, 1)
            self.frames[session] = frame
            self.labels[session] = title
            self.splitter.addWidget(frame)
            session.editable_split = self
            for signal, callback in (
                (session.canvas.pageChanged, lambda value, s=session: self.synchronize(s, "page", value)),
                (session.canvas.zoomChanged, lambda value, s=session: self.synchronize(s, "zoom", value)),
            ):
                signal.connect(callback)
                self._connections.append((signal, callback))
        app = QApplication.instance()
        app.installEventFilter(self)
        self.refresh_headers()
        self.reset_sizes()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.FocusIn, QEvent.Type.Wheel):
            for session, frame in self.frames.items():
                if watched is frame or (hasattr(watched, "parentWidget") and frame.isAncestorOf(watched)):
                    self.activate(session)
                    break
        return False

    def activate(self, session):
        if self.active is session:
            return
        self.active = session
        self.refresh_headers()
        self.workspace.tabChanged.emit(session)

    def refresh_headers(self):
        for session, title in self.labels.items():
            title.setText(("● " if session is self.active else "○ ") + session.tab_title)
            title.setToolTip(str(session.display_path or session.engine.original_path or "Untitled"))
            title.setAccessibleName(f"Edit {session.document_name}")
            frame = self.frames[session]
            # Use the theme's selection colour, rather than a fixed light/dark colour.
            frame.setStyleSheet(
                "QFrame#editablePdfPane { border: 2px solid palette(highlight); }"
                if session is self.active
                else "QFrame#editablePdfPane { border: 2px solid transparent; }"
            )

    def synchronize(self, source, kind, value):
        if self._syncing or not (self.sync_page if kind == "page" else self.sync_zoom):
            return
        other = next(s for s in self.sessions if s is not source)
        self._syncing = True
        try:
            if kind == "page":
                other.canvas.set_page(min(value, other.engine.page_count - 1))
            else:
                other.canvas.set_zoom(value)
        finally:
            self._syncing = False

    def set_orientation(self, orientation):
        self.splitter.setOrientation(
            Qt.Orientation.Vertical if orientation == "vertical" else Qt.Orientation.Horizontal
        )
        for session in self.sessions:
            session.split_orientation = orientation
        self.reset_sizes()

    def toggle_orientation(self):
        self.set_orientation(
            "vertical" if self.splitter.orientation() == Qt.Orientation.Horizontal else "horizontal"
        )

    def swap(self):
        self.splitter.insertWidget(0, self.splitter.widget(1))

    def reset_sizes(self):
        self.splitter.setSizes([1, 1])

    def release(self):
        QApplication.instance().removeEventFilter(self)
        for signal, callback in self._connections:
            signal.disconnect(callback)
        self._connections.clear()
        for session in self.sessions:
            session.editable_split = None
            session.tab_widget.setParent(self.workspace)
        self.frames.clear()
        self.labels.clear()
        self.hide()
        self.deleteLater()


class SessionOwnerRoute:
    """Connections resolve the current owner on delivery, including after a move."""

    def __init__(self, session):
        self.session = session

    def __getattr__(self, name):
        owner = self.session.window_owner
        value = getattr(owner, name)
        if not callable(value):
            return value

        def dispatch(*args, **kwargs):
            return getattr(self.session.window_owner, name)(*args, **kwargs)

        return dispatch
