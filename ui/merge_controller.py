"""Main-window routing for the isolated Merge tool tab."""
from PyQt6 import sip
from PyQt6.QtCore import Qt

from core.commands import Command, shortcut_conflict

from .merge_workspace import MergeWorkspace


class MergeController:
    def __init__(self, window):
        self.window = window
        self.previous_actions = {}
        self.exit_approved = False
        self.pdf_menus = list(window.menuBar().actions())
        self.shortcuts = {a: list(a.shortcuts()) for a in window._registered_shortcut_actions}
        # Merge replaces the PDF menus. Keep shared navigation shortcuts
        # associated with the window when their original menu is detached.
        for key in self.global_ids():
            if key in window._command_action_map:
                window.addAction(window._command_action_map[key])
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
        if tool:
            window.command_bar.set_document_available(False)
            # Merge is a PDF Workspace tab: keep shared tool navigation and
            # the user's expanded/collapsed choice. Only document tools are
            # unavailable while no PDF document tab is active.
            window.side_panel.set_document_available(False, unavailable_hint="Switch to a PDF tab to use this tool.")
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
            available = window.engine.is_loaded()
            window.side_panel.set_document_available(available, encrypted=available and window.engine.is_encrypted())
            window.command_bar.set_document_available(available)
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
        return WorkspaceModeController.GLOBAL | WorkspaceModeController.PDF_NAVIGATION

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
        bar._panel.setEnabled(True)
        page = self.window.workspace.current_tool()
        active = page is not None and self.pdf_active()
        if active:
            bar.set_shortcut_hints([Command(key, action.text(), action.shortcut().toString(), "Merge workspace",
                                  action.trigger, alternate_shortcuts=tuple(s.toString() for s in action.shortcuts()[1:]))
                                  for key, action in page.actions.items()])
            bar._save.setEnabled(not page.busy_state and not page.saving)
            bar._save_as.setEnabled(not page.busy_state and not page.saving)
            bar.set_undo_redo_enabled(page.undo.canUndo() and not page.busy_state, page.undo.canRedo() and not page.busy_state)
        else:
            bar.set_shortcut_hints(self.window._commands)

    def sync_activity(self):
        page = getattr(self.window, "_merge_workspace", None)
        self.window.command_bar.mode_switcher.set_busy("pdf", bool(self.window._tasks or (page and page.busy_state)))
        self.sync_controls()

    def commands(self, page):
        return [Command("merge."+key, action.text(), action.shortcut().toString(), "Merge workspace",
                        action.trigger, action.isEnabled,
                        alternate_shortcuts=tuple(s.toString() for s in action.shortcuts()[1:]))
                for key, action in page.actions.items()]

    def set_active(self, active):
        page = getattr(self.window, "_merge_workspace", None)
        if page:
            shared = [sequence.toString() for key, action in self.window._command_action_map.items()
                      if key in self.global_ids() for sequence in action.shortcuts()]
            shared.extend(shortcut.key().toString() for shortcut in self.window._command_shortcuts
                          if shortcut.property("commandId") in self.global_ids())
            for key, action in page.actions.items():
                sequences = page.shortcut_defaults.get(key, [])
                action.setShortcuts([s for s in sequences if not any(shortcut_conflict(s.toString(), value) for value in shared)]
                                    if active else [])
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
