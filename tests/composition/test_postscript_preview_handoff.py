"""Actual Ghostscript production preview handoff, including split output."""
from pathlib import Path

import pytest

from core.postscript_cache import PreviewCache, production_previews
from tests.composition.test_postscript import model, ps_media
from tests.production_approval import generate, overlay_generate


@pytest.mark.parametrize("kind", ["template", "overlay", "split", "workflow"])
def test_published_ps_first_open_reuses_interpreted_preview(tmp_path, monkeypatch, kind):
    from composition.media.postscript import ghostscript_executable
    from composition.production.model import ProductionJob
    from core import postscript_open
    cache = PreviewCache(tmp_path / "cache")
    with production_previews(cache):
        if kind == "workflow":
            from types import SimpleNamespace

            from composition.template.serializer import load_project, save_project
            from tests.production_approval import execute_batch
            from tests.test_mail_merge_workflow import pair, recipe
            from workflow.batch import BatchRun, approve, prepare
            from workflow.model import WorkflowNode
            job = pair(tmp_path, pages=3, records=2)
            template = load_project(job.template_path)
            template.media = ps_media("tray", duplex=True)
            save_project(template, job.template_path)
            spec = recipe([job]).upgraded(4)
            spec = spec.insert_after(spec.node("template").id, WorkflowNode("split_output", params={"method": "count", "count": 1}))
            run = prepare(spec, BatchRun(jobs=[job]), tmp_path / "check")
            approve(run, [job.id])
            execute_batch(spec, run, tmp_path / "workflow-output")
            assert job.status == "Completed", job.error
            result = SimpleNamespace(**job.result)
        elif kind == "overlay":
            from composition.overlay.model import OverlayJob
            from tests.composition.test_pdf_overlay_models import sample_spec
            spec = sample_spec(tmp_path)
            spec.media = ps_media("tray")
            result = overlay_generate(OverlayJob(spec.to_dict(), str(tmp_path / "output")))
        else:
            policy = {"envelopes": 1} if kind == "split" else {}
            result = generate(ProductionJob(model(ps_media(), count=2).to_dict(), "", str(tmp_path / "output"), output_policy=policy))
        assert result.status == "completed", result.error
    monkeypatch.setattr(postscript_open, "convert_ps", lambda *a, **k: pytest.fail("published PS was reinterpreted"))
    outputs = result.output_files
    assert len(outputs) == (2 if kind in {"split", "workflow"} else 1)
    for item in outputs:
        ps = Path(item["output_ps"])
        engine = postscript_open.open_postscript_engine(ps, ghostscript_executable(), cache=cache)
        try:
            assert engine.open_trace.values["ps_cache_hit"]
            assert engine.open_trace.values["ps_preview_profile"] == "production-v1"
            assert engine.page_count == item["pages"]
        finally:
            engine.close()


def test_optional_cache_store_failure_does_not_change_publication(tmp_path, monkeypatch):
    from composition.production.model import ProductionJob
    cache = PreviewCache(tmp_path / "cache")
    monkeypatch.setattr(cache, "store", lambda *a, **k: (_ for _ in ()).throw(PermissionError("unavailable")))
    with production_previews(cache):
        result = generate(ProductionJob(model(ps_media(), count=1).to_dict(), "", str(tmp_path / "output")))
    assert result.status == "completed", result.error
    assert Path(result.output_ps).is_file()
    assert (Path(result.report_dir) / "completion.json").is_file()
