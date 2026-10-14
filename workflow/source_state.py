"""Cheap source observations for UI freshness; production still verifies byte hashes."""
import os
from pathlib import Path


def pdf_sources(spec):
    paths=list(spec.node("input").params.get("paths",[]))
    overlay=spec.node("overlay")
    if overlay and overlay.params.get("path"):
        paths.append(overlay.params["path"])
    return paths


def observe_files(paths):
    result={}
    for raw in paths:
        if not raw:
            continue
        try:
            stat=Path(raw).stat()
            result[str(raw)]={"size":stat.st_size,"mtime_ns":stat.st_mtime_ns}
        except OSError:
            result[str(raw)]={"unavailable":True}
    return result


def validate_observations(observations):
    if not isinstance(observations,dict) or len(observations)>20000:
        raise ValueError("Invalid workflow source observations.")
    for path,value in observations.items():
        if not isinstance(path,str) or not path or len(path)>32768 or not isinstance(value,dict):
            raise ValueError("Invalid workflow source observation.")
        if value=={"unavailable":True}:
            continue
        if set(value)!={"size","mtime_ns"} or any(type(v) is not int or v<0 for v in value.values()):
            raise ValueError("Invalid workflow source observation.")


def changed_files(observations):
    validate_observations(observations)
    current=observe_files(observations)
    return [path for path in observations if current[path]!=observations[path]]


def path_key(path):
    # Avoid disk access on the GUI thread, including offline network paths.
    return os.path.normcase(os.path.abspath(path))


def invalidate_batch(batch,paths):
    keys={path_key(p) for p in paths}
    changed=[]
    for job in batch.jobs:
        sources=[job.template_path,job.data_path,*job.data_summary.get("source_observations",{})]
        if job.status=="Completed" or job.data_summary.get("stale") or not any(path_key(p) in keys for p in sources if p):
            continue
        job.approved=False
        job.status="Needs review"
        job.error="Source / open template changed. Save the template, then Check & Preview again."
        job.data_summary["stale"]=True
        changed.append(job.id)
    return changed
