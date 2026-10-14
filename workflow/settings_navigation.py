"""Route a review issue to the settings that actually supplied the job."""
import weakref


def issue_target(spec, context, issue):
    if issue.get("action")=="source":
        return "source",issue.get("path","")
    context=context or {}
    binding=context.get("binding",{})
    data=binding.get("data_summary",{})
    if issue.get("action")=="media" and data.get("media_source")=="workflow":
        node_id=data.get("media_node_id","")
        node=spec.node("media_assignment")
        return "node",node_id or (node.id if node else "")
    if issue.get("action")=="data":
        return "data",context.get("identity","")
    files=binding.get("files",[])
    template=next((str(p) for p in files if str(p).lower().endswith(".pdcx")),"")
    if template:
        return "project",template
    return "workflow",""


def return_link(project, window):
    project._workflow_origin=weakref.ref(window)
    if hasattr(project,"_return_workflow_action"):
        return
    from PyQt6 import sip
    from PyQt6.QtGui import QAction
    action=QAction("Return to Workflow",project)
    action.setToolTip("Return to the workflow that opened this template; save changes before checking again.")
    def back():
        origin=project._workflow_origin()
        if origin is not None and not sip.isdeleted(origin):
            origin.project_host.tabs.setCurrentWidget(origin)
    action.triggered.connect(back)
    toolbar=getattr(project,"project_toolbar",None) or getattr(project,"layout_toolbar",None)
    if toolbar:
        toolbar.addAction(action)
    else:
        project.menuBar().addAction(action)
    project._return_workflow_action=action


def open_design(window,path):
    if not window.project_host:
        window.message("Open this workflow in Document Designer to edit the source project.")
        return None
    project=window.project_host.open_project(path)
    if project:
        if hasattr(project,"return_to_design_settings"):
            project.return_to_design_settings()
        else:
            project.tabs.setCurrentIndex(0)
        return_link(project,window)
    return project


def edit_review_issue(window,context,issue):
    target,value=issue_target(window.spec,context,issue)
    if target=="source" and window.project_host:
        window.project_host.open_pdf_page(value,issue.get("page",0))
        return
    if target=="node":
        if any(n.id==value for n in window.spec.nodes):
            window.tabs.setCurrentWidget(getattr(window,"flow_page",None) or window.build_page)
            window.select_node(value)
            details=getattr(window,"inspector_scroll",getattr(window,"settings_scroll",None))
            if details:
                details.show()
            window.message("Edit the Workflow override here; project print settings are inherited only when selected.")
            return
    if target=="project":
        project=open_design(window,value)
        if project:
            if issue.get("action")=="media":
                project.edit_print_media()
            elif issue.get("object_id"):
                if hasattr(project,"template"):
                    for index,page in enumerate(project.template.pages):
                        if any(e.id==issue["object_id"] for e in page.elements):
                            project.select_template_page(index)
                            project.canvas.select_ids([issue["object_id"]])
                            project._show_properties(True)
                            break
                else:
                    project.canvas.select_ids([issue["object_id"]])
                    project.selection_changed()
                    project.inspector.show()
            return
    window.tabs.setCurrentWidget(window.review_page)
    if target=="data" and hasattr(window,"jobs_table"):
        for row,job in enumerate(window.batch.jobs):
            if job.id==value:
                index=window.proxy.mapFromSource(window.jobs_model.index(row,0))
                if not index.isValid():
                    window.job_filter.setCurrentIndex(0)
                    index=window.proxy.mapFromSource(window.jobs_model.index(row,0))
                window.jobs_table.selectRow(index.row())
                break
    window.message("Review the selected job and source settings. Check again after changes.")


def edit_project_media(window):
    """Edit inherited project settings without silently adding an override."""
    if window.active_worker or not window.flush_settings():
        return
    if hasattr(window,"edit_template"):
        project=window.edit_template()
    else:
        node=window.spec.node("overlay")
        project=open_design(window,node.params["path"]) if node and node.params.get("path") else None
        if not project:
            window.message("Choose a saved Overlay project for inherited settings, or select Workflow override.")
    if project:
        project.edit_print_media()
