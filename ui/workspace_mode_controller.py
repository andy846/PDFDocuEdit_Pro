"""Main-window integration only; PDF sessions and composition engines stay independent."""
from __future__ import annotations

from PyQt6 import sip
from PyQt6.QtCore import QObject
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QMenu, QVBoxLayout, QWidget

from core.commands import Command

from .workspace_modes import WorkspaceMode, WorkspaceModes


class WorkspaceModeController(QObject):
    GLOBAL = {"quit", "command_palette", "main_menu", "preferences", "about", "shortcuts", "readme", "document_designer", "visual_workflow"}

    def __init__(self, window, layout):
        super().__init__(window)
        self.window = window
        self.host = None
        self.exit_approved = False
        self.exit_preparing = False
        self.shutdown_started = False
        self.pdf_closed = False
        self.pdf_readers = []
        self.pdf_menus = list(window.menuBar().actions())
        self.pdf_bindings = {}
        self.project_bindings = {}
        self.modes = WorkspaceModes(window.centralWidget())
        pdf_page = QWidget()
        pdf_layout = QVBoxLayout(pdf_page)
        pdf_layout.setContentsMargins(0, 0, 0, 0)
        pdf_layout.setSpacing(0)
        for widget in (window.task_bar, window.splitter, window.bottom_bar):
            layout.removeWidget(widget)
            pdf_layout.addWidget(widget, 1 if widget is window.splitter else 0)
        window.info_bar.setParent(pdf_page)
        self.modes.add_mode(WorkspaceMode.PDF, pdf_page)
        layout.addWidget(self.modes, 1)
        self.workspace_menu = QMenu("&Workspace", window)
        self.designer_actions = {}
        for key, label, shortcut, callback in (
            ("new", "New project", "Ctrl+N", self.new_project),
            ("open", "Open Designer project…", "Ctrl+O", lambda: self.host.open_project()),
            ("overlay", "New PDF envelope overlay", "", lambda: self.host.new_overlay()),
            ("workflow", "New visual extraction workflow", "", lambda: self.host.new_workflow()),
            ("close", "Close project", "Ctrl+W", self.close_current_project),
            ("pdf", "Switch to PDF Workspace", "", lambda: self.request_mode("pdf")),
        ):
            action = QAction(label, window)
            action.triggered.connect(callback)
            action.setProperty("modeShortcut", shortcut)
            self.designer_actions[key] = action
            window.addAction(action)
            self.workspace_menu.addAction(action)
        entry=QAction("Visual extraction workflow…",window)
        entry.triggered.connect(self.new_workflow)
        window.addAction(entry)
        window.command_bar._pdf_more_menu.addAction(entry)
        window._command_action_map["visual_workflow"]=entry
        window._commands.append(Command("visual_workflow","Visual extraction workflow","","PDF production",self.new_workflow,entry.isEnabled))
        self.capture_pdf_bindings()
        # Keep application-wide actions available when PDF menus are detached.
        for key, action in window._command_action_map.items():
            if key in self.GLOBAL:
                window.addAction(action)
                self.workspace_menu.addAction(action)
        self.modes.modeChanged.connect(self.sync_mode)
        window.command_bar.modeRequested.connect(self.request_mode)
        window.task_bar.activityChanged.connect(lambda busy: window.command_bar.mode_switcher.set_busy("pdf",
            busy or bool(getattr(getattr(window, "_merge_workspace", None), "busy_state", False))))
        self.set_animations_enabled(bool(window.settings.get("animations_enabled", True)))
        self.sync_mode("pdf")
        from .workspace_handoff import WorkspaceHandoffService
        self.handoff = WorkspaceHandoffService(self)

    def request_mode(self, mode):
        mode = WorkspaceMode(mode)
        if self.exit_approved:
            return
        if mode == WorkspaceMode.DESIGNER:
            self.ensure_host()
        self.modes.request_mode(mode)

    def ensure_host(self, *, create_default=True):
        if self.host is None:
            from composition.designer.project_host import DesignerProjectHost
            self.host = DesignerProjectHost(self.modes, open_pdf=lambda path: self.window.queue_open_files([str(path)]))
            self.host.handoff = self.handoff
            self.host.set_animations_enabled(bool(self.window.settings.get("animations_enabled", True)))
            self.host.projectAdded.connect(self.project_added)
            self.host.projectRemoved.connect(self.project_removed)
            self.host.activeProjectChanged.connect(self.project_changed)
            self.host.activityChanged.connect(self.activity_changed)
            self.modes.add_mode(WorkspaceMode.DESIGNER, self.host)
            if create_default:
                self.host.new_template()
        return self.host

    def capture_pdf_bindings(self):
        self.pdf_bindings = {action: list(action.shortcuts()) for action in self.window._registered_shortcut_actions}

    def project_added(self, project):
        self.handoff.attach_project(project)
        self.project_bindings[project] = {action: list(action.shortcuts()) for action in project.findChildren(QAction) if action.shortcuts()}
        self.sync_bindings()

    def project_removed(self, project):
        self.project_bindings.pop(project, None)
        self.handoff.remove_project(project)

    def activity_changed(self):
        busy = self.host and any(self.host.is_busy(p) for p in self.host.projects)
        self.window.command_bar.mode_switcher.set_busy("designer", bool(busy))

    def project_changed(self):
        if not self.exit_approved and self.modes.mode == WorkspaceMode.DESIGNER:
            self.sync_mode("designer")

    def new_workflow(self):
        host=self.ensure_host(create_default=False)
        self.request_mode("designer")
        return host.new_workflow()

    def new_project(self):
        current = self.host.current_project
        if current and getattr(current,"is_workflow",False):
            return self.host.new_workflow()
        return self.host.new_overlay() if current and not hasattr(current, "template") else self.host.new_template()

    def close_current_project(self):
        if self.host and self.host.current_project:
            self.host.close_project(self.host.current_project)

    def sync_bindings(self):
        pdf = self.modes.mode == WorkspaceMode.PDF
        tool = self.window.workspace.current_tool()
        global_actions = {action for key, action in self.window._command_action_map.items() if key in self.GLOBAL}
        for action, sequences in self.pdf_bindings.items():
            action.setShortcuts(sequences if (pdf and tool is None) or action in global_actions else [])
        for shortcut in self.window._command_shortcuts:
            shortcut.setEnabled((pdf and tool is None) or shortcut.property("commandId") in self.GLOBAL)
        current = self.host.current_project if self.host else None
        for project, bindings in self.project_bindings.items():
            # New/Open/Close belong to the host, including its empty state.
            host_actions = {project.actions.get(key) for key in ("new", "open", "close", "source")}
            for action, sequences in bindings.items():
                if sip.isdeleted(action):
                    continue
                action.setShortcuts(sequences if not pdf and project is current and action not in host_actions else [])
        for key, action in self.designer_actions.items():
            action.setShortcut(QKeySequence(str(action.property("modeShortcut"))) if not pdf else QKeySequence())
            action.setEnabled(not pdf and (key != "close" or current is not None))

    def sync_mode(self, mode):
        self.sync_bindings()
        window = self.window
        window.command_bar.set_mode(mode)
        menus = window.menuBar()
        menus.clear()
        if mode == WorkspaceMode.PDF:
            tool = window.workspace.current_tool()
            if tool:
                menus.addMenu(tool.menu)
                for key in self.GLOBAL:
                    if key in window._command_action_map:
                        menus.addAction(window._command_action_map[key])
            else:
                for action in self.pdf_menus:
                    menus.addAction(action)
        else:
            menus.addMenu(self.workspace_menu)
            project = self.host.current_project if self.host else None
            if project:
                for action in project.menuBar().actions():
                    menus.addAction(action)
        window.command_bar.set_application_menu(menus)
        merge = getattr(window, "_merge_controller", None)
        if merge:
            merge.set_active(mode == WorkspaceMode.PDF and window.workspace.current_tool() is not None)
        if window._integrated_chrome:
            menus.hide()
        palette = getattr(window, "_command_palette", None)
        if palette:
            palette._commands = self.commands()
            palette.refresh()

    def commands(self):
        if self.modes.mode == WorkspaceMode.PDF:
            tool = self.window.workspace.current_tool()
            if tool:
                return [c for c in self.window._commands if c.id in self.GLOBAL] + self.window._merge_controller.commands(tool)
            return [*self.window._commands, Command("send_to_designer", "Send current PDF to Designer", "",
                    "Workspace handoff", lambda: self.handoff.send_pdf(self.window._session), self.handoff.send_button.isEnabled)]
        commands = [c for c in self.window._commands if c.id in self.GLOBAL]
        for key, action in self.designer_actions.items():
            commands.append(Command("designer.host." + key, action.text().replace("&", ""),
                                    str(action.property("modeShortcut")), "Designer workspace", action.trigger, action.isEnabled))
        project = self.host.current_project if self.host else None
        if project:
            bindings = self.project_bindings.get(project, {})
            for key, action in project.actions.items():
                if key in {"new", "open", "close"}:
                    continue
                sequences = bindings.get(action, [])
                commands.append(Command("designer." + key, action.text().replace("&", ""),
                                        sequences[0].toString() if sequences else "", "Document Designer", action.trigger, action.isEnabled))
        return commands

    def set_animations_enabled(self, enabled):
        self.modes.set_animations_enabled(enabled)
        if self.host:
            self.host.set_animations_enabled(enabled)

    def prepare_exit(self):
        merge_page = getattr(self.window, "_merge_workspace", None)
        if merge_page and merge_page.capture_count:
            self.window.info_bar.show_message("Finish capturing open PDFs before exiting.", "warning")
            return False
        if self.host and any(getattr(p,"capture_active",False) for p in self.host.projects):
            self.window.info_bar.show_message("Finish capturing PDFs for Workflow before exiting.", "warning")
            return False
        if self.handoff.capture_active:
            self.window.info_bar.show_message("Cancel or finish the PDF handoff before exiting.", "warning")
            return False
        if self.exit_approved:
            return True
        if self.exit_preparing:
            return False
        self.exit_preparing = True
        window = self.window
        previous = window._session
        window._mode_exit_preflight = True
        try:
            merge = getattr(window, "_merge_controller", None)
            if merge and not merge.confirm_exit():
                return False
            for session in list(window._sessions):
                window._session = session
                if not window._confirm_discard_changes():
                    return False
            if self.host and not self.host.confirm_all():
                return False
        finally:
            window._session = previous
            window._mode_exit_preflight = False
            self.exit_preparing = False
        self.exit_approved = True
        window.setEnabled(False)
        return True

    def shutdown_workspaces(self):
        window = self.window
        if not self.shutdown_started:
            self.shutdown_started = True
            window._closing = True
            window._queued_open_paths.clear()
            for task in list(window._tasks):
                task.cancel()
        designer_ready = self.host is None or self.host.shutdown()
        merge = getattr(window, "_merge_controller", None)
        merge_ready = merge is None or merge.shutdown()
        if window._tasks:
            return False
        if not self.pdf_closed:
            self.pdf_closed = True
            for session in list(window._sessions):
                self.pdf_readers.extend(session.canvas.reader_events())
                self.pdf_readers.extend(session.nav_panel.thumbnails.reader_events())
                if session.split_canvas is not None:
                    self.pdf_readers.extend(session.split_canvas.reader_events())
                session.close()
        return designer_ready and merge_ready and all(event.is_set() for event in self.pdf_readers)
