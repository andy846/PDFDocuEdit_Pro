"""Observe source freshness on return without synchronous filesystem I/O in Qt."""
from copy import deepcopy

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QTimer

from .source_state import invalidate_batch, path_key


class SourceWatch(QObject):
    def __init__(self,window):
        super().__init__(window)
        self.window=window
        self.worker=None
        self.notifying=False
        self.timer=QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.check)
        window.installEventFilter(self)
        window.tabs.currentChanged.connect(self.schedule)
        if window.project_host:
            window.project_host.activeProjectChanged.connect(self.schedule)
            window.project_host.activityChanged.connect(self.open_changes)

    def eventFilter(self,watched,event):
        if event.type()==QEvent.Type.WindowActivate:
            self.schedule()
        return False

    def schedule(self,*_):
        self.timer.start()

    def observations(self):
        w=self.window
        controller=getattr(w,"inspections",None)
        checked={p:v for item in getattr(controller,"results",{}).values() if item.get("status")=="Checked"
                 for p,v in item.get("source_observations",{}).items()}
        # Formal job/data acceptance owns its older baseline even if a newer
        # ad-hoc inspection exists. A step check cannot refresh that acceptance.
        if hasattr(w,"batch"):
            checked.update({p:v for j in w.batch.jobs if j.status!="Completed"
                for p,v in j.data_summary.get("source_observations",{}).items()})
        elif isinstance(w.run,dict):
            checked.update(w.run.get("source_observations",{}))
            checked.update({p:v for j in w.run.get("jobs",[]) if j["status"]!="Completed"
                for raw in j.get("batch",{}).get("jobs",[]) for p,v in raw.get("data_summary",{}).get("source_observations",{}).items()})
        else:
            checked.update(w.run.data_summary.get("source_observations",{}))
        return checked

    def open_changes(self,*_):
        w=self.window
        if self.notifying or w.active_worker or not w.project_host:
            return
        watched={path_key(p) for p in self.observations()}
        changed=[]
        for project in w.project_host.projects:
            if project is w or not project.project_path:
                continue
            if path_key(str(project.project_path)) in watched and (not project.undo.isClean() or
                    getattr(project,"content_invalid",False) or getattr(project,"draft_error","") or
                    getattr(project.properties,"has_batch_draft",lambda:False)()):
                changed.append(str(project.project_path))
        self.invalidate(changed)

    def check(self):
        w=self.window
        if sip.isdeleted(w) or w.close_pending or w.active_worker or self.worker or w.workers:
            return
        if w.project_host and w.project_host.current_project is not w:
            return
        observations=deepcopy(self.observations())
        if not observations:
            return
        from composition.designer.process import Worker
        worker=Worker(w.directory,{"task":"workflow","operation":"source_status","observations":observations},w)
        self.worker=worker
        w.workers.append(worker)
        result=[]
        worker.resultReady.connect(result.append)
        def ended():
            if worker in w.workers:
                w.workers.remove(worker)
            self.worker=None
            if not w.close_pending and result and observations==self.observations():
                self.invalidate(result[0]["changed"])
            if w.close_pending and not w.workers:
                QTimer.singleShot(0,w.close)
        worker.ended.connect(ended)

    def invalidate(self,paths):
        w=self.window
        if not paths or self.notifying:
            return
        changed=False
        self.notifying=True
        try:
            if hasattr(w,"batch"):
                changed=bool(invalidate_batch(w.batch,paths))
                if changed:
                    w.changed_jobs()
            elif isinstance(w.run,dict):
                from .batch import BatchRun
                for entry in w.run.get("jobs",[]):
                    if entry["status"]=="Completed":
                        continue
                    batch=BatchRun.from_dict(entry["batch"])
                    shared={path_key(p) for p in w.run.get("source_observations",{})}
                    affected=[j.template_path for j in batch.jobs] if shared.intersection(path_key(p) for p in paths) else paths
                    if invalidate_batch(batch,affected):
                        entry["batch"]=batch.to_dict()
                        entry.update(approved=False,status="Needs review",error=batch.jobs[0].error)
                        changed=True
                if changed:
                    w.run["stale"]=True
                    w.refresh_results()
            elif not w.run.data_summary.get("stale"):
                keys={path_key(p) for p in paths}
                if any(path_key(p) in keys for p in self.observations()):
                    w.run.data_summary["stale"]=True
                    w.run.accepted=False
                    w.run.error="Source / Overlay project changed. Save changes, then scan and review again."
                    review=w.spec.node("review")
                    w.run.statuses[review.id]="Needs review"
                    w.canvas.display(w.spec,w.run.statuses,w.selected)
                    changed=True
            if changed:
                inspections=getattr(w,"inspections",None)
                if inspections:
                    for item in inspections.results.values():
                        item["status"]="Out of date"
                    inspections.refresh()
                if hasattr(w,"production_review"):
                    w.production_review.invalidate()
                w.message("Source / open project changed — Check & Preview again. Completed outputs are preserved.")
        finally:
            self.notifying=False
