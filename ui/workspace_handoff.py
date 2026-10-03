"""PDF/Designer handoffs, independent of editor rendering and composition widgets."""
from __future__ import annotations

import copy
import tempfile
import time
from bisect import bisect_right
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
)

from composition.handoff import capture_pdf
from composition.overlay.geometry import check_object_bounds
from composition.overlay.model import EnvelopeSpec
from composition.pdf_source.model import EnvelopeSettings
from composition.pdf_source.planner import EnvelopePlan
from composition.template.model import MM_TO_PT, CompositionError
from styles.theme import get_color

from .icons import icon


class WorkspaceHandoffService(QObject):
    def __init__(self, controller):
        super().__init__(controller)
        self.controller, self.window = controller, controller.window
        self.links, self.outputs = {}, {}
        self.geometry_cache = {}
        self._icon_color = None
        self.pending = False
        self.capture_active = False
        self.source_dirs = {}
        bar = self.window.command_bar
        self.send_button = QToolButton(bar)
        self.send_button.setObjectName("sendToDesigner")
        self.send_button.setIcon(icon("arrow-up-right"))
        self.send_button.setText("Send to Designer")
        self.send_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.send_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.send_button.setToolTip("Send the current PDF, including unsaved edits, to Document Designer")
        self.send_button.clicked.connect(lambda: self.send_pdf(self.window._session))
        menu = QMenu(self.send_button)
        self.send_actions = []
        for text, callback in (
            ("Entire PDF overlay", lambda: self.send_pdf(self.window._session)),
            ("Current page overlay", lambda: self.send_pdf(self.window._session, pages=[self.window._session.page])),
            ("Current page as template background", lambda: self.send_pdf(self.window._session, "template_background", [self.window._session.page])),
            ("Create separate overlay project", lambda: self.send_pdf(self.window._session, force_new=True)),
        ):
            action = QAction(text, menu)
            action.triggered.connect(callback)
            menu.addAction(action)
            self.send_actions.append(action)
        self.send_button.setMenu(menu)
        bar.layout().insertWidget(bar.layout().indexOf(bar.mode_switcher)+1, self.send_button)
        self.back_button = QToolButton(bar)
        self.back_button.setIcon(icon("chevron-left"))
        self.back_button.setText("Back to Designer")
        self.back_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.back_button.clicked.connect(self.back_to_project)
        self.back_button.hide()
        bar.layout().insertWidget(bar.layout().indexOf(self.send_button)+1, self.back_button)
        self.origin_action = menu.addAction("Open original source page", self.open_output_source)
        self.origin_action.setEnabled(False)
        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        controller.modes.modeChanged.connect(self.refresh)
        self.window.workspace.tabChanged.connect(lambda *args: self.refresh())
        self.refresh()

    @staticmethod
    def model(project):
        return project.template if hasattr(project, "template") else project.spec

    def link(self, project):
        model = self.model(project)
        return model.source_link if model else {}

    def attach_project(self, project):
        group = QGroupBox("Linked PDF")
        group.setObjectName("linkedPdfPanel")
        group.setStyleSheet("QGroupBox#linkedPdfPanel { padding-left: 0px; padding-right: 0px; }")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        label = QLabel()
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(label)
        open_button, update_button = QPushButton("Open source"), QPushButton("Update source")
        open_button.setToolTip("Open source in PDF Workspace / locate and reconnect original PDF")
        update_button.setToolTip("Update from PDF Workspace while keeping Designer objects and fonts")
        for button in (open_button, update_button):
            button.setProperty("compact", True)
            layout.addWidget(button)
        open_button.clicked.connect(lambda: self.open_linked_source(project))
        update_button.clicked.connect(lambda: self.update_source(project))
        parent_layout = project.data_content.layout() if hasattr(project, "template") else project.source_summary.parentWidget().layout()
        parent_layout.insertWidget(0, group)
        project.link_panel, project.link_status = group, label
        project.link_update = update_button
        project.link_open = open_button
        group.hide()
        project.undo.indexChanged.connect(lambda *args: self.refresh())
        project.activityChanged.connect(lambda *args: self.refresh())
        project.windowTitleChanged.connect(lambda *args: self.refresh())
        self.refresh()

    def remove_project(self, project):
        self.links.pop(project, None)
        self.geometry_cache.pop(project, None)
        self.outputs = {session: data for session, data in self.outputs.items() if data["project"] is not project}
        for directory in self.source_dirs.pop(project, []):
            directory.cleanup()
        self.refresh()

    def refresh(self, *args):
        if getattr(self.window, "_closing", False):
            return
        color = get_color("text_primary")
        if color != self._icon_color:
            self._icon_color = color
            self.send_button.setIcon(icon("arrow-up-right", color=color))
            self.back_button.setIcon(icon("chevron-left", color=color))
        pdf_mode = self.controller.modes.mode.value == "pdf"
        session = self.window._session
        busy = self.pending or bool(self.window._tasks) or self.window._printing
        self.send_button.setVisible(pdf_mode and self.window.workspace.current_tool() is None)
        self.send_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon
                                           if self.window.command_bar.width() >= 1000 else Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.send_button.setEnabled(pdf_mode and self.window.workspace.current_tool() is None
                                    and session is not None and session.engine.is_loaded() and not busy)
        for action in self.send_actions:
            action.setEnabled(self.send_button.isEnabled())
        output = self.outputs.get(session)
        self.back_button.setVisible(pdf_mode and output is not None)
        if output:
            stale = session.engine.is_modified or session.engine.revision != output["revision"]
            self.back_button.setToolTip("Output edited: production QC applies to the original generated file."
                                        if stale else "Return to the project without losing PDF review position")
            self.back_button.setText("Edited · Designer" if stale else "Back to Designer")
            self.back_button.setToolButtonStyle(self.send_button.toolButtonStyle())
        self.origin_action.setEnabled(bool(output and output.get("spec")))
        if output and (output.get("template") or {}).get("source_link"):
            self.origin_action.setEnabled(True)
        if self.capture_active:
            return  # Never enter the live engine's global lock from a GUI timer.
        host = self.controller.host
        for project in host.projects if host else []:
            if not hasattr(project, "link_panel"):
                continue
            link = self.link(project)
            project.link_panel.setVisible(bool(link))
            if not link:
                continue
            scroll = project.data_panel if hasattr(project, "template") else project.source_scroll
            minimum = scroll.widget().minimumSizeHint().width() + scroll.verticalScrollBar().sizeHint().width() + 2
            scroll.setMinimumWidth(minimum)
            if not hasattr(project, "template"):
                scroll.setMaximumWidth(max(260, minimum))
            binding = self.links.get(project)
            connected = binding and binding["session"] in self.window._sessions
            if connected:
                current = binding["session"].engine
                connected = current.is_loaded() and current.document_id == binding["document_id"]
            state = "Source disconnected — saved snapshot retained"
            if connected:
                state = "Up to date" if current.revision == binding["revision"] and link["transfer_id"] == binding["transfer_id"] else "Source changed"
            blocked = link.get("review_required", False)
            project.link_status.setText(f"{link['label']}\n{len(link['page_map']):,} source page(s) · {state}\n"
                                       + ("Grouping not confirmed / source review required" if blocked else "") )
            project.link_status.setToolTip(f"Captured: {link['captured_at']}\n{link['original_path']}")
            project.link_update.setEnabled(bool(connected) and not self.project_busy(project) and not busy)
            if not hasattr(project, "template") and project.spec:
                cached = self.geometry_cache.get(project)
                if cached is None or cached[0] is not project.spec:
                    cached = (project.spec, self.geometry_issues(project.spec))
                    self.geometry_cache[project] = cached
                issues = cached[1]
                if issues:
                    project.link_status.setText(project.link_status.text()+"\n"+issues[0])
                    project.actions["generate"].setEnabled(False)

    @staticmethod
    def project_busy(project):
        return bool(getattr(project, "active_worker", None) or getattr(project, "production_worker", None)
                    or getattr(project, "import_worker", None) or getattr(project, "font_token", None)
                    or getattr(project, "font_requests", {}) or getattr(project, "content_invalid", False)
                    or getattr(project, "draft_error", "") or project.close_pending)

    @staticmethod
    def geometry_issues(spec):
        issues = []
        for obj in spec.objects:
            for geometry in spec.source.geometries:
                try:
                    check_object_bounds(obj.element, geometry)
                except CompositionError as error:
                    issues.append(str(error))
                    break
        return issues

    def send_pdf(self, session, purpose="overlay", pages=None, *, force_new=False):
        if session is None or session not in self.window._sessions or not session.engine.is_loaded():
            return
        if self.pending or self.window._tasks or self.window._printing:
            self.message("Wait for the current operation before handing off a PDF.")
            return
        chosen = None if pages is None else sorted(set(pages))
        if chosen == []:
            return
        identity = (session.engine.document_id, session.engine.revision)
        for project, binding in list(self.links.items()):
            if not force_new and binding["session"] is session and binding["purpose"] == purpose and binding["pages"] == chosen:
                if binding["revision"] == identity[1] and self.link(project).get("transfer_id") == binding["transfer_id"]:
                    self.focus_project(project)
                    return project
                if QMessageBox.question(self.window, "Linked project", "Update the linked Designer project with the current PDF?\nChoose No to create a separate project.") == QMessageBox.StandardButton.Yes:
                    return self.update_source(project, session)
                break
        return self._capture(session, purpose, chosen)

    def update_source(self, project, session=None):
        binding = self.links.get(project)
        session = session or (binding["session"] if binding else None)
        if not session or session not in self.window._sessions:
            self.message("Reconnect the original PDF before updating. The saved snapshot remains usable.")
            return
        if self.project_busy(project):
            self.message("Finish generation, import or the unfinished edit before updating the source.")
            return
        link = self.link(project)
        pages = binding["pages"] if binding else (None if link.get("selection") == "all" else link["page_map"])
        return self._capture(session, link["purpose"], pages, project)

    def _capture(self, session, purpose, pages, project=None):
        if self.pending or self.window._tasks or self.window._printing:
            return
        self.window.workspace.set_current_session(session)
        if session.form_draft and session.form_draft.changed:
            prompt = QMessageBox(self.window)
            prompt.setWindowTitle("Unapplied form draft")
            prompt.setText("Apply the form draft before PDF handoff?")
            apply = prompt.addButton("Apply draft", QMessageBox.ButtonRole.AcceptRole)
            discard = prompt.addButton("Send without draft", QMessageBox.ButtonRole.ActionRole)
            prompt.addButton(QMessageBox.StandardButton.Cancel)
            prompt.exec()
            if prompt.clickedButton() is apply:
                if not self.window._apply_form_draft():
                    return
            elif prompt.clickedButton() is not discard:
                return
        identity = (session.engine.document_id, session.engine.revision)
        directory = tempfile.TemporaryDirectory(prefix="pdfdocuedit-handoff-")
        self.pending = self.capture_active = True
        self.refresh()
        session.tab_widget.setEnabled(False)
        pdf_page = self.controller.modes.pages["pdf"]
        pdf_enabled = pdf_page.isEnabled()
        pdf_page.setEnabled(False)
        pdf_actions = [(action, action.isEnabled()) for action in self.controller.pdf_bindings
                       if action not in {self.window._command_action_map[key] for key in self.controller.GLOBAL
                                         if key in self.window._command_action_map}]
        pdf_buttons = [(button, button.isEnabled()) for button in self.window.command_bar.findChildren(QToolButton)]
        for action, _ in pdf_actions:
            action.setEnabled(False)
        for button, _ in pdf_buttons:
            button.setEnabled(False)
        adopted = False

        def ready(result):
            nonlocal adopted
            if session not in self.window._sessions or identity != (session.engine.document_id, session.engine.revision):
                self.message("Source changed or closed. Send the current PDF again.")
                return
            if project and (project not in self.controller.host.projects or self.project_busy(project)):
                self.message("Target project is busy or closed. Its source was retained.")
                return
            source, link = result
            if project:
                old = self.model(project)
                old_pages = len(old.source_link.get("page_map", []))
                geom = source.geometries[0]
                old_geom = old.source.geometries[0] if hasattr(old, "source") else {
                    "width_pt": old.pages[0].width_mm*MM_TO_PT, "height_pt": old.pages[0].height_mm*MM_TO_PT, "rotation": 0}
                summary = (f"Source pages: {old_pages:,} → {source.pages:,}\n"
                           f"Old page: {old_geom['width_pt']/MM_TO_PT:.2f} × {old_geom['height_pt']/MM_TO_PT:.2f} mm; rotation {old_geom['rotation']}°\n"
                           f"New page: {geom['width_pt']/MM_TO_PT:.2f} × {geom['height_pt']/MM_TO_PT:.2f} mm; rotation {geom['rotation']}°\n"
                           "Objects and fonts are retained. Review grouping and object positions before generation.")
                if QMessageBox.question(self.window, "Update linked PDF", summary) != QMessageBox.StandardButton.Yes:
                    return
            self.controller.ensure_host(create_default=False)
            target = project or (self.controller.host.new_template() if purpose == "template_background" else self.controller.host.new_overlay())
            if not target:
                return
            if purpose == "overlay":
                if project:
                    raw = target.spec.to_dict()
                    raw["source"] = copy.deepcopy(source.__dict__)
                    raw["source_link"] = link
                    if raw["settings"]["groups"]:
                        raw["settings"].update(pages_per_envelope=1, groups=[], excluded_pages=[])
                        raw["detection_review"] = {"required": True, "accepted": False, "source_sha256": source.sha256}
                    elif source.pages % raw["settings"]["pages_per_envelope"]:
                        raw["settings"]["pages_per_envelope"] = 1
                    raw["detection_review"] = raw["detection_review"] if raw["detection_review"].get("required") else {}
                    if not target.commit(raw, "Update linked PDF source"):
                        return
                else:
                    spec = EnvelopeSpec(source, EnvelopeSettings(pages_per_envelope=1), name=link["label"], source_link=link)
                    target.apply_spec(spec.to_dict())
                    target.undo.resetClean()
            else:
                before, raw = target.template.to_dict(), target.template.to_dict()
                page_id = self.link(target).get("page_id", target.active_page_id)
                page = next((item for item in raw["pages"] if item["id"] == page_id), None)
                if page is None:
                    self.message("The linked template page was removed. Create a new background handoff.")
                    return
                geom = source.geometries[0]
                page.update(background=source.path, width_mm=geom["width_pt"]/MM_TO_PT, height_mm=geom["height_pt"]/MM_TO_PT)
                link["page_id"] = page_id
                raw["source_link"] = link
                raw["name"] = target.template.name if project else link["label"]
                target._commit(before, raw, "Update PDF background" if project else "Use workspace PDF background", page_id=target.active_page_id)
            self.source_dirs.setdefault(target, []).append(directory)
            adopted = True
            self.links[target] = {"session": session, "document_id": identity[0], "revision": identity[1],
                                  "transfer_id": link["transfer_id"], "purpose": purpose, "pages": pages}
            self.focus_project(target)
            if not project:
                target.canvas.fit_page()
            self.refresh()

        def finished():
            self.pending = self.capture_active = False
            if not sip.isdeleted(pdf_page):
                pdf_page.setEnabled(pdf_enabled)
            for action, enabled in pdf_actions:
                if not sip.isdeleted(action):
                    action.setEnabled(enabled)
            for button, enabled in pdf_buttons:
                if not sip.isdeleted(button):
                    button.setEnabled(enabled)
            if session in self.window._sessions and not sip.isdeleted(session.tab_widget):
                session.tab_widget.setEnabled(True)
            if not adopted:
                directory.cleanup()
            self.refresh()

        self.window._run_task("Sending PDF to Document Designer", capture_pdf, session.engine, directory.name, identity,
                              pages=pages, purpose=purpose, source_label=session.document_name,
                              original_path=str(session.display_path or session.engine.original_path or ""),
                              progress_argument="progress", cancel_argument="is_cancelled", on_result=ready,
                              on_finished=finished, on_discard=lambda result: directory.cleanup())

    def focus_project(self, project):
        self.controller.request_mode("designer")
        self.controller.host.tabs.setCurrentWidget(project)

    def open_linked_source(self, project, page=None):
        binding = self.links.get(project)
        if binding and binding["session"] in self.window._sessions:
            session = binding["session"]
            if session.engine.document_id == binding["document_id"]:
                self.controller.request_mode("pdf")
                self.window.workspace.set_current_session(session)
                if page is not None and 0 <= page < session.engine.page_count:
                    self.window.goto_page(page)
                return
        link = self.link(project)
        path = link.get("original_path", "")
        if not path or not Path(path).is_file():
            path, _ = QFileDialog.getOpenFileName(self.window, "Locate original PDF to reconnect", "", "PDF (*.pdf)")
        if not path:
            return
        if QMessageBox.question(self.window, "Reconnect PDF", "Open this PDF as the linked source?\nThe Designer keeps its saved snapshot until you explicitly update it.") != QMessageBox.StandardButton.Yes:
            return
        self.window.queue_open_files([str(path)])
        self._when_open(path, lambda session: self._reconnect(project, session, page))

    def _reconnect(self, project, session, page):
        if project not in self.controller.host.projects:
            return
        link = self.link(project)
        self.links[project] = {"session": session, "document_id": session.engine.document_id, "revision": -1,
                               "transfer_id": link["transfer_id"], "purpose": link["purpose"],
                               "pages": None if link.get("selection") == "all" else link["page_map"]}
        self.controller.request_mode("pdf")
        self.window.workspace.set_current_session(session)
        if page is not None and 0 <= page < session.engine.page_count:
            self.window.goto_page(page)
        self.refresh()

    def open_production_output(self, project, result):
        path = result["output_pdf"]
        if not path:
            return
        self.window.queue_open_files([path])
        spec = copy.deepcopy(getattr(project, "_output_spec", None))
        template = copy.deepcopy(getattr(project, "_output_template", None))
        def opened(session):
            plan = EnvelopePlan(spec["source"]["pages"], EnvelopeSettings(**spec["settings"])) if spec else None
            self.outputs[session] = {"project": project, "revision": session.engine.revision, "spec": spec,
                                     "template": template, "plan": plan}
            self.refresh()
        self._when_open(path, opened)

    def _when_open(self, path, callback):
        deadline = time.monotonic() + 45
        def check():
            if getattr(self.window, "_closing", False):
                return
            for session in self.window._sessions:
                existing = session.display_path or session.engine.original_path
                if existing and Path(existing).resolve() == Path(path).resolve():
                    callback(session)
                    return
            if time.monotonic() < deadline:
                QTimer.singleShot(100, check)
        QTimer.singleShot(0, check)

    def back_to_project(self):
        data = self.outputs.get(self.window._session)
        if data and data["project"] in self.controller.host.projects:
            self.focus_project(data["project"])

    def open_output_source(self):
        session = self.window._session
        data = self.outputs.get(session)
        if not data:
            return
        if not data["spec"]:
            template = data.get("template")
            link = template.get("source_link", {}) if template else {}
            if not link:
                return
            if session.engine.is_modified or session.engine.revision != data["revision"]:
                self.message("Output was edited; its original page mapping cannot be assumed.")
                return
            page = template["pages"][session.page % len(template["pages"])]
            if page["id"] != link.get("page_id"):
                self.message("This template page has no linked original PDF background.")
                return
            original = link["page_map"][0]
        else:
            return self._open_overlay_source(session, data)
        if not self._source_mapping_current(data["project"], link):
            return
        self.open_linked_source(data["project"], original)

    def _source_mapping_current(self, project, link):
        binding = self.links.get(project)
        if self.link(project).get("sha256") != link.get("sha256") or (binding and binding["session"] in self.window._sessions
                and binding["session"].engine.revision != binding["revision"]):
            self.message("Original PDF changed since production. Its current page numbers cannot be assumed; the original production report is retained.")
            return False
        return True

    def _open_overlay_source(self, session, data):
        plan, spec = data["plan"], data["spec"]
        output_page = session.page + 1
        if not 1 <= output_page <= plan.output_pages:
            self.message("This edited output page has no verified source mapping.")
            return
        if session.engine.is_modified or session.engine.revision != data["revision"]:
            self.message("Output was edited; its original page mapping cannot be assumed. Open the original output to trace pages.")
            return
        envelope = bisect_right(plan.output_starts, output_page) if plan.groups else (output_page-1)//plan.settings.output_pages_per_envelope+1
        start = plan.output_starts[envelope-1] if plan.groups else (envelope-1)*plan.settings.output_pages_per_envelope+1
        source_page = plan.page(envelope, output_page-start+1).source_page
        if source_page is None:
            self.message("Inserted blank back — no original source page.")
            return
        link = spec.get("source_link", {})
        if link and not self._source_mapping_current(data["project"], link):
            return
        original = link["page_map"][source_page-1] if link else source_page-1
        self.open_linked_source(data["project"], original)

    def message(self, text):
        self.window.info_bar.show_message(text, "warning")
