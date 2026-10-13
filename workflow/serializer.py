"""Portable declarative workflow files with content-addressed PDF/project assets."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from composition.overlay.serializer import load_project as load_overlay
from composition.overlay.serializer import save_project as save_overlay
from composition.production.generator import check_cancel
from composition.template.model import CompositionError
from composition.template.serializer import file_hash
from core.io_atomic import atomic_output

from .model import WorkflowSpec


def save_workflow(spec, path, *, is_cancelled=None):
    spec.validate()
    target=Path(path).resolve().with_suffix(".pdflow")
    assets=target.parent/(target.stem+".assets")
    value=WorkflowSpec.from_dict(spec.to_dict())
    if value.workflow_version==5:
        from composition.template.serializer import load_project, save_project
        for node in value.nodes:
            if node.kind=="template" and node.params.get("path"):
                check_cancel(is_cancelled)
                original=Path(node.params["path"]).resolve()
                assets.mkdir(parents=True,exist_ok=True)
                copied=save_project(load_project(original),assets/(file_hash(original)[:20]+".pdcx"))
                node.params["path"]=Path(copied).relative_to(target.parent).as_posix()
        # Source data stays external. Save paths relative when practical.
        import os
        for item in value.node("for_each").params.get("items",[]):
            try:
                item["path"]=os.path.relpath(item["path"],target.parent)
            except ValueError:
                pass  # A source on another Windows drive remains an absolute reference.
    source=value.node("input")
    old_paths=source.params.get("paths",[]) if source else []
    new_paths=[]
    for raw in old_paths:
        check_cancel(is_cancelled)
        original=Path(raw).resolve()
        digest=file_hash(original)
        assets.mkdir(parents=True,exist_ok=True)
        copied=assets/(digest+".pdf")
        if copied.exists() and file_hash(copied)!=digest:
            raise CompositionError("Saved source asset changed; choose another save location.")
        if not copied.exists():
            with atomic_output(copied,overwrite=False) as temp:
                shutil.copyfile(original,temp)
                if file_hash(temp)!=digest:
                    raise CompositionError("Source changed during save.")
        new_paths.append(copied.relative_to(target.parent).as_posix())
    if source:
        source.params["paths"]=new_paths
    merge=value.node("merge")
    if merge:
        selections=merge.params.get("pages",{})
        merge.params["pages"]={new:selections.get(old,"All") for old,new in zip(old_paths,new_paths,strict=True)}
    overlay=value.node("overlay")
    if overlay and overlay.params.get("path"):
        project=load_overlay(overlay.params["path"])
        assets.mkdir(parents=True,exist_ok=True)
        source_file=Path(project.source.path)
        source_digest=file_hash(source_file)
        source_copy=assets/(source_digest+".pdf")
        if not source_copy.exists():
            with atomic_output(source_copy,overwrite=False) as temp:
                shutil.copyfile(source_file,temp)
                if file_hash(temp)!=source_digest:
                    raise CompositionError("Overlay source changed during save.")
        if file_hash(source_copy)!=source_digest:
            raise CompositionError("Saved overlay source asset changed.")
        project.source.path=str(source_copy.resolve())
        project.source.size=source_copy.stat().st_size
        project.source.mtime_ns=source_copy.stat().st_mtime_ns
        digest=file_hash(Path(overlay.params["path"]))
        copied=save_overlay(project,assets/(digest+".pdcx"))
        overlay.params["path"]=copied.relative_to(target.parent).as_posix()
    check_cancel(is_cancelled)
    with atomic_output(target) as temp:
        temp.write_text(json.dumps(value.to_dict(),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return str(target)


def load_workflow(path):
    target=Path(path).resolve()
    if target.stat().st_size>16*1024*1024:
        raise CompositionError("Workflow exceeds 16 MB.")
    spec=WorkflowSpec.from_dict(json.loads(target.read_text(encoding="utf-8")))
    if spec.workflow_version==5:
        for item in spec.node("for_each").params.get("items",[]):
            item["path"]=str((target.parent/item["path"]).resolve())
        for node in spec.nodes:
            if node.kind=="template" and node.params.get("path"):
                node.params["path"]=str((target.parent/node.params["path"]).resolve())
    source=spec.node("input")
    if source:
        paths=source.params.get("paths",[])
        if not isinstance(paths,list) or len(paths)>10000 or any(not isinstance(p,str) or len(p)>4096 for p in paths):
            raise CompositionError("Invalid source path list.")
        resolved=[str((target.parent/p).resolve()) for p in paths]
        merge=spec.node("merge")
        if merge:
            selections=merge.params.get("pages",{})
            merge.params["pages"]={new:selections.get(old,"All") for old,new in zip(paths,resolved,strict=True)}
        source.params["paths"]=resolved
    overlay=spec.node("overlay")
    if overlay and overlay.params.get("path"):
        overlay.params["path"]=str((target.parent/overlay.params["path"]).resolve())
    return spec
