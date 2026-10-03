"""Main-window routing for the isolated Merge tool tab."""
from PyQt6 import sip
from PyQt6.QtCore import Qt

from core.commands import Command

from .merge_workspace import MergeWorkspace


class MergeController:
    def __init__(self, window):
        self.window = window
        self.previous_actions = {}
        self.sidebar_hidden = None
        self.exit_approved = False
        self.pdf_menus = list(window.menuBar().actions())
        self.shortcuts = {a: list(a.shortcuts()) for a in window._registered_shortcut_actions}
        window.workspace.toolTabChanged.connect(self.active_changed)
        window.workspace.toolTabCloseRequested.connect(lambda tool: tool.request_close())

    def open(self):
        window = self.window
        mode = getattr(window, "_mode_controller", None)
        if mode:
            mode.request_mode("pdf")
        page = getattr(window, "_merge_workspace", None)
        if page is None or page.stopped:
            page = MergeWorkspace(window)
            window._merge_workspace = page
            page.titleChanged.connect(lambda title: self.update_title(page, title))
            page.activityChanged.connect(lambda busy: self.sync_activity())
            page.undo.indexChanged.connect(lambda *_: self.sync_controls())
            page.undo.cleanChanged.connect(lambda *_: self.sync_controls())
            window.workspace.add_tool_tab("merge", page, "Merge PDFs")
        else:
            window.workspace._tabs.setCurrentWidget(page)
        self.active_changed(page)
        return page

    def update_title(self, page, title):
        if sip.isdeleted(self.window.workspace._tabs):
            return
        index = self.window.workspace._tabs.indexOf(page)
        if index >= 0:
            self.window.workspace._tabs.setTabText(index, title)

    def active_changed(self, tool):
        window = self.window
        if sip.isdeleted(window.workspace._tabs) or getattr(window, "_closing", False):
            return
        if tool and not self.previous_actions:
            self.previous_actions = {action: action.isEnabled() for action in window._registered_shortcut_actions}
            self.sidebar_hidden = window.side_panel.isHidden()
        if tool:
            window.command_bar.set_document_available(False)
            window.side_panel.hide()
            keep = self.global_ids() | {"merge"}
            for key, action in window._command_action_map.items():
                if key not in keep:
                    action.setEnabled(False)
            window.bottom_bar.hide()
            window._hide_context()
        else:
            for action, enabled in self.previous_actions.items():
                action.setEnabled(enabled)
            self.previous_actions.clear()
            if self.sidebar_hidden is not None:
                window.side_panel.setVisible(not self.sidebar_hidden)
                self.sidebar_hidden = None
            window.command_bar.set_document_available(window.engine.is_loaded())
            window.bottom_bar.show()
        mode = getattr(window, "_mode_controller", None)
        if mode:
            mode.sync_mode(mode.modes.mode)
        else:
            for action, sequences in self.shortcuts.items():
                action.setShortcuts([] if tool and action not in [window._command_action_map[k] for k in self.global_ids() if k in window._command_action_map] else sequences)
            for shortcut in window._command_shortcuts:
                shortcut.setEnabled(tool is None or shortcut.property("commandId") in self.global_ids())
            menus = window.menuBar()
            menus.clear()
            if tool:
                menus.addMenu(tool.menu)
                for key in self.global_ids():
                    if key in window._command_action_map:
                        menus.addAction(window._command_action_map[key])
            else:
                for action in self.pdf_menus:
                    menus.addAction(action)
            window.command_bar.set_application_menu(menus)
        self.sync_controls()

    @staticmethod
    def global_ids():
        from .workspace_mode_controller import WorkspaceModeController
        return WorkspaceModeController.GLOBAL

    def pdf_active(self):
        mode = getattr(self.window, "_mode_controller", None)
        return mode is None or mode.modes.mode.value == "pdf"

    def route(self, key, fallback):
        page = self.window.workspace.current_tool()
        if page and self.pdf_active():
            action = page.actions.get(key)
            if action and action.isEnabled():
                action.trigger()
            return
        fallback()

    def sync_controls(self):
        if sip.isdeleted(self.window.workspace._tabs) or getattr(self.window, "_closing", False):
            return
        bar = self.window.command_bar
        page = self.window.workspace.current_tool()
        active = page is not None and self.pdf_active()
        if active:
            bar._open.setToolTip("Open merge list (Ctrl+O)")
            bar._save.setToolTip("Save merge list (Ctrl+S)")
            bar._save.setEnabled(not page.busy_state and not page.saving)
            bar._save_as.setEnabled(not page.busy_state and not page.saving)
            bar._panel.setEnabled(False)
            bar.set_undo_redo_enabled(page.undo.canUndo() and not page.busy_state, page.undo.canRedo() and not page.busy_state)
        else:
            bar._open.setToolTip("Open PDF (Ctrl+O)")
            bar._save.setToolTip("Save (Ctrl+S)")
            bar._panel.setEnabled(True)

    def sync_activity(self):
        page = getattr(self.window, "_merge_workspace", None)
        self.window.command_bar.mode_switcher.set_busy("pdf", bool(self.window._tasks or (page and page.busy_state)))
        self.sync_controls()

    def commands(self, page):
        return [Command("merge."+key, action.text(), action.shortcut().toString(), "Merge workspace",
                        action.trigger, action.isEnabled) for key, action in page.actions.items()]

    def set_active(self, active):
        page = getattr(self.window, "_merge_workspace", None)
        if page:
            for action in page.actions.values():
                if not active:
                    action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
                else:
                    action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

    def confirm_exit(self):
        page = getattr(self.window, "_merge_workspace", None)
        return page is None or page.confirm_discard(after_save=self.window.close)

    def prepare_exit(self):
        if self.exit_approved:
            return True
        page = getattr(self.window, "_merge_workspace", None)
        if page and page.capture_count:
            page.error("Finish capturing open PDFs before exiting.")
            return False
        if not self.confirm_exit():
            return False
        previous = self.window._session
        try:
            for session in self.window._sessions:
                self.window._session = session
                if not self.window._confirm_discard_changes():
                    return False
        finally:
            self.window._session = previous
        self.exit_approved = True
        self.window.setEnabled(False)
        return True

    def shutdown(self):
        page = getattr(self.window, "_merge_workspace", None)
        if not page:
            return True
        page.stop()
        return not page.workers
