"""Persistent Designer project tabs; close confirmation is separate from shutdown."""
from __future__ import annotations

import json
import os
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QEventLoop, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QStackedWidget,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class DesignerProjectHost(QWidget):
    activeProjectChanged = pyqtSignal()
    activityChanged = pyqtSignal()
    projectAdded = pyqtSignal(object)
    projectRemoved = pyqtSignal(object)

    def __init__(self, parent=None, *, open_pdf=None, open_pdf_page=None):
        super().__init__(parent)
        self.open_pdf = open_pdf or (lambda path: None)
        self.open_pdf_page = open_pdf_page or (lambda path, page: self.open_pdf(path))
        self.handoff = None
        self.shutting_down = False
        self.close_buttons = {}
        self.animations_enabled = True
        self.tabs = QTabWidget()
        self.tabs.setObjectName("designerProjectTabs")
        self.tabs.tabBar().setObjectName("designerProjectTabBar")
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(False)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(lambda index: self.close_project(self.tabs.widget(index)))
        self.tabs.currentChanged.connect(lambda *args: self.activeProjectChanged.emit())
        from .home import DesignerHome
        self.start = DesignerHome(self)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.start)
        self.stack.addWidget(self.tabs)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

    @property
    def projects(self):
        return [self.tabs.widget(index) for index in range(self.tabs.count())]

    def open_production_output(self, project, result):
        if self.handoff:
            return self.handoff.open_production_output(project, result)
        return self.open_pdf(result["output_pdf"])

    def open_source_pdf(self, path, page=0):
        """Navigate to a checked source page through the existing PDF open service."""
        if self.handoff:
            window = self.handoff.window
            self.handoff.controller.request_mode("pdf")
            return window.open_in_new_tab(str(path), on_open=lambda session: window._session_goto(session, page))
        return self.open_pdf(path)

    @property
    def current_project(self):
        return self.tabs.currentWidget()

    @staticmethod
    def identity(path):
        return os.path.normcase(str(Path(path).expanduser().resolve()))

    def _append(self, project):
        from ui.workspace import TabCloseButton

        project.menuBar().hide()
        index = self.tabs.addTab(project, "Untitled")
        close_button = TabCloseButton()
        close_button.setToolTip("Close Designer project")
        close_button.setAccessibleName("Close Designer project")
        close_button.set_animations_enabled(self.animations_enabled)
        close_button.clicked.connect(lambda checked=False, p=project: self.close_project(p))
        self.tabs.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, close_button)
        self.close_buttons[project] = close_button
        project.windowTitleChanged.connect(lambda *args, p=project: self.update_project(p))
        project.activityChanged.connect(lambda p=project: self.update_project(p))
        project.undo.indexChanged.connect(lambda *args, p=project: self.update_project(p))
        project.properties.edited.connect(lambda *args, p=project: self.update_project(p))
        project.projectClosed.connect(lambda p=project: self.remove_project(p))
        self.projectAdded.emit(project)
        self.tabs.setCurrentIndex(index)
        self.stack.setCurrentWidget(self.tabs)
        self.update_project(project)
        self.activeProjectChanged.emit()
        return project

    def set_animations_enabled(self, enabled):
        self.animations_enabled = bool(enabled)
        for button in self.close_buttons.values():
            button.set_animations_enabled(self.animations_enabled)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange):
            for button in getattr(self, "close_buttons", {}).values():
                button.refresh_icon()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,"start"):
            QTimer.singleShot(0,self.start.arrange)

    def new_template(self):
        if self.shutting_down:
            return None
        from .workspace import CompositionWindow
        return self._append(CompositionWindow(self.tabs, embedded=True, project_host=self))

    def new_workflow(self):
        if self.shutting_down:
            return None
        from workflow.workspace import WorkflowWindow
        return self._append(WorkflowWindow(self.tabs, embedded=True, project_host=self))

    def choose_workflow(self):
        label,ok=QInputDialog.getItem(self,"Create Visual Workflow","Production workflow",
            ["Conditional Mail Merge · For each file + template routes","Mail Merge Production · Letter templates + data","PDF Processing · Extract, group and overlay"],0,False)
        if ok:
            return self.new_branch_workflow() if label.startswith("Conditional") else self.new_mail_merge_workflow() if label.startswith("Mail Merge") else self.new_workflow()

    def new_branch_workflow(self):
        if self.shutting_down:
            return None
        from workflow.branch_ui import BranchWorkflowWindow
        return self._append(BranchWorkflowWindow(self.tabs,embedded=True,project_host=self))

    def new_mail_merge_workflow(self):
        if self.shutting_down:
            return None
        from workflow.mail_merge_ui import MailMergeWorkflowWindow
        return self._append(MailMergeWorkflowWindow(self.tabs,embedded=True,project_host=self))

    def workflow_from_project(self,project):
        if project.properties.apply() is False or getattr(project,"content_invalid",False):
            return None
        if self.is_busy(project):
            project._error("Finish the template's task before creating a workflow.")
            return None
        if not project.project_path or not project.undo.isClean():
            if not project.save_project():
                return None
        from workflow.batch import BatchJob
        workflow=self.new_mail_merge_workflow()
        workflow.batch.jobs=[BatchJob(name=project.template.name[:200] or "Letter job",template_path=str(project.project_path),
            data_path=project.template.data.path,data_options={k:v for k,v in vars(project.template.data).items() if k!="path"},
            output_name="letters.pdf")]
        workflow.changed_jobs()
        workflow.tabs.setCurrentWidget(workflow.review_page)
        return workflow

    def new_overlay(self):
        if self.shutting_down:
            return None
        from .overlay_workspace import OverlayWindow
        return self._append(OverlayWindow(self.tabs, embedded=True, project_host=self))

    def open_project(self, path=None):
        if self.shutting_down:
            return None
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open Document Designer project", "", "Designer projects (*.pdcx *.pdflow)")
        if not path:
            return None
        key = self.identity(path)
        for project in self.projects:
            if project.project_path and self.identity(project.project_path) == key:
                self.tabs.setCurrentWidget(project)
                return project
        try:
            file = Path(path)
            if file.stat().st_size > 10 * 1024 * 1024:
                raise ValueError("Designer project exceeds 10 MB.")
            raw = json.loads(file.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("Invalid Designer project structure.")
            if raw.get("project_kind") in ("pdf_workflow","mail_merge_workflow"):
                from workflow.serializer import load_workflow
                load_workflow(path)
                project = self.new_branch_workflow() if raw.get("workflow_version")==5 else self.new_mail_merge_workflow() if raw["project_kind"]=="mail_merge_workflow" else self.new_workflow()
                project.project_path=Path(path).resolve()
                project.load_path(path)
            elif raw.get("project_kind") == "pdf_overlay":
                from composition.overlay.serializer import load_project
                load_project(path)
                project = self.new_overlay()
                project.load_path(path)
            else:
                from composition.template.serializer import load_project
                load_project(path)
                project = self.new_template()
                project.project_host = None
                try:
                    project.open_project(path=path)
                finally:
                    project.project_host = self
            self.update_project(project)
            return project
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.warning(self, "Cannot open project", str(exc))
            return None

    def allow_save_path(self, project, path):
        key = self.identity(Path(path).with_suffix(".pdflow" if getattr(project,"is_workflow",False) else ".pdcx"))
        if any(p is not project and p.project_path and self.identity(p.project_path) == key for p in self.projects):
            QMessageBox.warning(self, "Project already open", "This file is open in another Designer tab. Switch to that tab or choose another filename.")
            return False
        return True

    @staticmethod
    def is_busy(project):
        return bool(getattr(project, "production_worker", None) or getattr(project, "import_worker", None)
                    or getattr(project, "active_worker", None) or getattr(project, "font_requests", None)
                    or getattr(project, "batch_pending", False) or getattr(project, "font_token", None) or getattr(project,"capture_active",False) or getattr(project,"workflow_binding",False))

    def update_project(self, project):
        if sip.isdeleted(self) or sip.isdeleted(project) or sip.isdeleted(self.tabs):
            return
        index = self.tabs.indexOf(project)
        if index < 0:
            return
        if project.project_path and getattr(project,"_recent_path",None)!=str(project.project_path):
            from .recents import remember
            remember(project.project_path,"Workflow" if getattr(project,"is_workflow",False) else
                     "Template" if hasattr(project,"template") else "Overlay")
            project._recent_path=str(project.project_path)
        kind = "Workflow" if getattr(project,"is_workflow",False) else "Template Designer" if hasattr(project, "template") else "Overlay"
        model = project.template if hasattr(project, "template") else project.spec
        name = project.project_path.name if project.project_path else model.name if model and (getattr(model,"source_link",None) or getattr(project,"is_workflow",False)) else "Untitled"
        dirty = not project.undo.isClean() or bool(getattr(project,"batch_dirty",False) or getattr(project, "content_invalid", False) or getattr(project, "draft_error", "") or (getattr(project, "batch_editor", None) and project.properties.has_batch_draft()))
        self.tabs.setTabText(index, f"{kind} · {name}" + (" *" if dirty else "") + (" ●" if self.is_busy(project) else ""))
        self.tabs.setTabToolTip(index, project.windowTitle())
        self.activityChanged.emit()

    def confirm_project_close(self, project):
        # Never discard a draft during preflight: a later project may cancel application exit.
        if not self.is_busy(project):
            if project.properties.apply() is False:
                return False
        dirty = not project.undo.isClean() or bool(getattr(project,"batch_dirty",False) or getattr(project, "content_invalid", False) or getattr(project, "draft_error", "") or (getattr(project, "batch_editor", None) and project.properties.has_batch_draft()))
        editor = getattr(project, "batch_editor", None)
        if editor and editor.deferred_discard:
            dirty = not project.undo.isClean() or bool(getattr(project, "content_invalid", False) or getattr(project, "draft_error", ""))
        if not dirty:
            return True
        answer = QMessageBox.question(self, "Unsaved Designer project", "Save changes to " + (project.project_path.name if project.project_path else "this project") + "?",
                    QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Discard:
            return True
        if hasattr(project, "template"):
            return bool(project.save_project())
        if self.is_busy(project) or project.draft_error:
            project.error("Finish or revert the unfinished edit and wait for the active task before saving.")
            return False
        completed = []
        loop = QEventLoop(self)
        project.save_project(after=lambda: (completed.append(True), loop.quit()))
        worker = project.active_worker
        if worker is None:
            return False
        worker.failed.connect(lambda *args: loop.quit())
        loop.exec()
        return bool(completed)

    def confirm_all(self):
        editors = [p.batch_editor for p in self.projects if hasattr(p, "batch_editor")]
        for editor in editors:
            editor.defer_discard = True
        try:
            return all(self.confirm_project_close(project) for project in self.projects)
        finally:
            for editor in editors:
                editor.defer_discard = editor.deferred_discard = False

    def close_project(self, project, *, approved=False):
        if project not in self.projects:
            return True
        if not approved and not project.close_pending and not self.confirm_project_close(project):
            return False
        project._close_approved = True
        project.close()
        return project not in self.projects

    def remove_project(self, project):
        index = self.tabs.indexOf(project)
        if index >= 0:
            button = self.close_buttons.pop(project, None)
            if button:
                self.tabs.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, None)
                button.deleteLater()
            self.tabs.removeTab(index)
        self.projectRemoved.emit(project)
        if not self.tabs.count():
            self.stack.setCurrentWidget(self.start)
        self.activeProjectChanged.emit()
        self.activityChanged.emit()

    def shutdown(self):
        self.shutting_down = True
        for project in self.projects:
            self.close_project(project, approved=True)
        return not self.projects
