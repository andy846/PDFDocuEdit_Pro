"""In-process PDF window ownership, safe live-session moves and tab dragging."""

from __future__ import annotations

import os
import uuid

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QMimeData, QObject, QPoint, QPointF, Qt, QTimer
from PyQt6.QtGui import QAction, QCursor, QDrag
from PyQt6.QtWidgets import QApplication

TAB_MIME = "application/x-pdfdocuedit-live-tab"


class DocumentWindows(QObject):
    def __init__(self, primary):
        super().__init__(QApplication.instance())
        self.primary = primary
        self.windows = []
        self.last_active = primary
        self.pending_exit = False
        self._drag_session = None
        self._drag_token = None
        self._press = None
        self._dragging = False
        QApplication.instance().installEventFilter(self)

    def register(self, window):
        self.windows.append(window)
        window.workspace.move_reason = lambda session: (
            self.busy_reason(window)
            or ("Document access is currently locked." if not window.isEnabled() or self.pending_exit else "")
            or ("Open a PDF before moving this tab." if not session.engine.is_loaded() else "")
        )
        window.workspace.window_targets = lambda: [
            (
                ("Main window" if w is self.primary else "PDF window")
                + " · "
                + (w._session.document_name if w._session else "No document"),
                w,
            )
            for w in self.live_windows()
            if w is not window
        ]
        window.workspace.splitWithRequested.connect(window._split_documents)
        window.workspace.moveWindowRequested.connect(lambda session, target: self.move(session, target))
        window.workspace._tabs.tabBar().installEventFilter(self)
        window.workspace._tabs.tabBar().setAcceptDrops(True)
        window.workspace.setAcceptDrops(True)
        window.workspace.installEventFilter(self)
        if window is not self.primary:
            action = window._command_action_map.get("quit")
            if action:
                action.triggered.disconnect()
                action.triggered.connect(self.primary.close)
            update = window._command_action_map.get("check_updates")
            if update:
                update.triggered.disconnect()
                update.triggered.connect(self.primary._check_for_updates)
            account = self.primary.findChild(QAction, "privateAccountAction")
            if account:
                alias = QAction(account.icon(), account.text(), window)
                alias.setObjectName("privateAccountAction")
                alias.triggered.connect(account.trigger)

                def mirror_account():
                    if not sip.isdeleted(alias):
                        alias.setText(account.text())
                        alias.setToolTip(account.toolTip())
                        alias.setEnabled(account.isEnabled())

                account.changed.connect(mirror_account)
                mirror_account()
                window.command_bar.add_settings_action(alias)
            window.command_bar.mode_switcher.hide()

    def window_closed(self, window):
        if window in self.windows:
            self.windows.remove(window)
        if not self.windows:
            QApplication.instance().removeEventFilter(self)
            self.setParent(None)

    def live_windows(self):
        return [w for w in self.windows if not sip.isdeleted(w) and not getattr(w, "_window_closed", False)]

    def active_window(self):
        return self.last_active if self.last_active in self.live_windows() else self.primary

    def find_path(self, path):
        identity = os.path.normcase(os.path.abspath(os.path.expanduser(str(path))))
        for window in self.live_windows():
            for session in window._sessions:
                source = session.display_path or session.engine.original_path
                if source and os.path.normcase(os.path.abspath(str(source))) == identity:
                    return window, session
        return None

    def focus(self, window, session=None):
        controller = getattr(window, "_mode_controller", None)
        if controller:
            controller.request_mode("pdf")
        if session is not None:
            window.workspace.set_current_session(session)
        window.showNormal() if window.isMinimized() else window.show()
        window.raise_()
        window.activateWindow()
        self.last_active = window

    def busy_reason(self, window):
        if window._printing:
            return "Finish printing before moving documents."
        if window._tasks or window._queued_open_paths:
            return "Wait for the current PDF task to finish before moving documents."
        for tool in window.workspace._tool_tabs:
            controller = getattr(tool, "controller", None)
            if (
                getattr(tool, "workers", None)
                or getattr(tool, "capture_count", 0)
                or (controller and getattr(controller, "busy", False))
            ):
                return "Finish the PDF tool task before moving documents."
        for name in ("_merge_workspace", "_pdf_production_workspace"):
            tool = getattr(window, name, None)
            if tool and (getattr(tool, "busy_state", False) or getattr(tool, "capture_count", 0)):
                return "Finish the PDF tool task before moving documents."
        controller = getattr(window, "_mode_controller", None)
        if controller and controller.handoff.capture_active:
            return "Finish the document handoff before moving documents."
        if any(getattr(d, "worker", None) for d in getattr(window, "_pdf_operation_dialogs", [])):
            return "Finish the PDF operation before moving documents."
        if any(getattr(d, "_task", None) for d in getattr(window, "_comparison_dialogs", [])):
            return "Finish the comparison before moving documents."
        return ""

    def move(self, session, target=None):
        source = session.window_owner
        if source not in self.live_windows() or session not in source._sessions:
            return False
        reason = self.busy_reason(source)
        if target is not None:
            if target not in self.live_windows():
                return False
            reason = reason or self.busy_reason(target)
        if reason or not source.isEnabled() or self.pending_exit:
            source.info_bar.show_message(reason or "Document access is currently locked.", "warning")
            return False
        if target is source:
            return True
        created = target is None
        if created:
            from core.viewer import PDFViewer

            try:
                target = PDFViewer(pdf_only=True, document_windows=self)
            except Exception as exc:
                source.info_bar.show_message(f"Unable to create PDF window: {exc}", "error")
                return False
            target.settings = self.primary.settings
            target.resize(source.size())
            target.move(source.pos() + QPoint(30, 30))
        old_index = None
        try:
            old_index = source.workspace.take_session(session)
            source._sessions.remove(session)
            session.window_owner = target
            session.setParent(target)
            target._sessions.append(session)
            target.workspace.attach_session(session)
            source._session = source.workspace.current_session()
            if source._session is not None:
                source._on_tab_changed(source._session)
            else:
                source._hide_context()
                source._set_document_available(False)
                source.bottom_bar.set_document_info("No document", 0)
                source._sync_modified_state()
            source._refresh_all_split_source_choices()
            target._refresh_all_split_source_choices()
            self.focus(target, session)
            source.info_bar.show_message(
                "Document moved; unsaved changes and undo history retained.", "success"
            )
            return True
        except Exception as exc:
            if session in target._sessions:
                if session in target.workspace._sessions.values():
                    target.workspace.take_session(session)
                target._sessions.remove(session)
            session.window_owner = source
            session.setParent(source)
            if session not in source._sessions:
                source._sessions.append(session)
            if session not in source.workspace._sessions.values():
                source.workspace.attach_session(session, old_index)
            source.workspace.set_current_session(session)
            source.info_bar.show_message(f"Unable to move document: {exc}", "error")
            if created:
                target.close()
            return False

    def prepare_application_close(self):
        others = [w for w in self.live_windows() if w is not self.primary]
        if not others:
            return True
        if not self.pending_exit:
            approved = []
            for window in [self.primary, *others]:
                window._exit_previous_enabled = window.isEnabled()
                dialog = getattr(window, "_update_dialog", None)
                if window._printing or (dialog is not None and dialog.busy()):
                    self.primary.info_bar.show_message(
                        "Finish printing or the update download before exiting.", "warning"
                    )
                    self._reset_approvals(approved)
                    return False
                controller = getattr(window, "_mode_controller", None)
                if controller:
                    ok = controller.prepare_exit()
                else:
                    previous = window._session
                    window._mode_exit_preflight = True
                    try:
                        merge = getattr(window, "_merge_controller", None)
                        ok = merge is None or merge.confirm_exit()
                        for session in list(window._sessions) if ok else []:
                            window._session = session
                            if not window._confirm_discard_changes():
                                ok = False
                                break
                    finally:
                        window._session = previous
                        window._mode_exit_preflight = False
                if not ok:
                    self._reset_approvals(approved)
                    return False
                window._window_exit_approved = True
                merge = getattr(window, "_merge_controller", None)
                if merge:
                    merge.exit_approved = True
                approved.append(window)
            self.pending_exit = True
            for window in approved:
                window.setEnabled(False)
        for window in others:
            window.close()
        if any(w.isVisible() for w in others):
            QTimer.singleShot(150, self.primary.close)
            return False
        return True

    @staticmethod
    def _reset_approvals(windows):
        for window in windows:
            window._window_exit_approved = False
            controller = getattr(window, "_mode_controller", None)
            if controller:
                controller.exit_approved = False
            merge = getattr(window, "_merge_controller", None)
            if merge:
                merge.exit_approved = False
            window.setEnabled(getattr(window, "_exit_previous_enabled", True))

    def sync_theme(self, source, value):
        if getattr(self, "_theme_syncing", False):
            return
        self._theme_syncing = True
        try:
            for window in self.live_windows():
                if window is not source:
                    window._apply_theme(value)
        finally:
            self._theme_syncing = False

    def set_locked(self, locked):
        for window in self.live_windows():
            if window is self.primary:
                continue
            window.setEnabled(not locked)
            if locked:
                window._queued_open_paths.clear()
                window._pending_searches.clear()
                window._cancel_tasks()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.WindowActivate and watched in self.live_windows():
            self.last_active = watched
        workspace = next(
            (
                w.workspace
                for w in self.live_windows()
                if watched in (w.workspace, w.workspace._tabs.tabBar())
            ),
            None,
        )
        if workspace is None:
            return False
        bar = workspace._tabs.tabBar()
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and watched is bar
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._press = (
                workspace,
                workspace.session_at(bar.tabAt(event.position().toPoint())),
                event.position().toPoint(),
            )
        elif (
            event.type() == QEvent.Type.MouseMove
            and watched is bar
            and self._press
            and event.buttons() & Qt.MouseButton.LeftButton
            and not self._dragging
        ):
            origin, session, point = self._press
            global_point = event.globalPosition().toPoint()
            if (
                session is not None
                and origin is workspace
                and not workspace.window().frameGeometry().contains(global_point)
                and (event.position().toPoint() - point).manhattanLength() >= QApplication.startDragDistance()
            ):
                self._press = None
                QTimer.singleShot(0, lambda s=session, b=bar: self.start_drag(s, b))
                return True
        elif event.type() == QEvent.Type.MouseButtonRelease:
            self._press = None
        elif event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
            if not event.mimeData().hasFormat(TAB_MIME):
                return False
            token = bytes(event.mimeData().data(TAB_MIME)).decode("ascii", errors="replace")
            if token != self._drag_token or self._drag_session is None:
                event.ignore()
                return True
            if event.type() == QEvent.Type.Drop:
                target = workspace.window()
                if self.move(self._drag_session, target):
                    event.setDropAction(Qt.DropAction.MoveAction)
                    event.accept()
                else:
                    event.ignore()
            else:
                event.setDropAction(Qt.DropAction.MoveAction)
                event.accept()
            return True
        return False

    def start_drag(self, session, bar):
        if self.busy_reason(session.window_owner) or not session.window_owner.isEnabled():
            self.move(session, session.window_owner)
            return
        # Finish QTabBar's internal reorder gesture before entering QDrag's loop.
        from PyQt6.QtGui import QMouseEvent

        release = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(bar.mapFromGlobal(QCursor.pos())),
            QPointF(QCursor.pos()),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(bar, release)
        self._drag_session = session
        self._drag_token = uuid.uuid4().hex
        self._dragging = True
        mime = QMimeData()
        mime.setData(TAB_MIME, self._drag_token.encode("ascii"))
        drag = QDrag(bar)
        drag.setMimeData(mime)
        self._drag_cancelled = False
        self._escape_filter = DragEscape(self)
        QApplication.instance().installEventFilter(self._escape_filter)
        try:
            result = drag.exec(Qt.DropAction.MoveAction)
            if result == Qt.DropAction.IgnoreAction and not self._drag_cancelled:
                point = QCursor.pos()
                if not any(w.frameGeometry().contains(point) for w in self.live_windows()):
                    if self.move(session):
                        session.window_owner.move(point - QPoint(80, 20))
        finally:
            QApplication.instance().removeEventFilter(self._escape_filter)
            self._escape_filter.deleteLater()
            self._dragging = False
            self._drag_session = None
            self._drag_token = None
            drag.deleteLater()


class DragEscape(QObject):
    def __init__(self, manager):
        super().__init__(manager)
        self.manager = manager

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.manager._drag_cancelled = True
        return False
