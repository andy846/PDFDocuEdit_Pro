"""Save-only recovery using existing serializers, with no production dispatch."""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal


class DraftSaveThread(QThread):
    saved = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, request, parent):
        super().__init__(parent)
        self.request = request

    def run(self):
        try:
            self.saved.emit(save_draft(self.request))
        except Exception:
            self.failed.emit("Could not save this draft. Your open work is retained.")
        finally:
            self.request = None


def save_draft(request):
    task = request.get("task")
    if task == "save":
        from composition.template.model import Template
        from composition.template.serializer import load_project, save_project
        path = save_project(Template.from_dict(request["template"]), request["target"])
        return {"project": str(path), "template": load_project(path).to_dict()}
    if task == "overlay_save":
        from composition.overlay.model import EnvelopeSpec
        from composition.overlay.serializer import load_project, save_project
        path = save_project(EnvelopeSpec.from_dict(request["project"]), request["target"])
        return {"project": str(path), "spec": load_project(path).to_dict()}
    if task == "workflow" and request.get("operation") == "save":
        from workflow.model import WorkflowSpec
        from workflow.serializer import save_workflow
        return {"path": str(save_workflow(WorkflowSpec.from_dict(request["spec"]), request["path"]))}
    raise ValueError("Only saving an existing draft is permitted during recovery.")
