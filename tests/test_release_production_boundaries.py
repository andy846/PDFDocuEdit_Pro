"""Release review regressions against real approval, publication and recovery."""
import copy
import json
import shutil
import sqlite3
from dataclasses import asdict
from pathlib import Path

import pytest

from composition.template.model import CompositionError, Element
from composition.template.serializer import load_project, save_project
from tests.test_mail_merge_workflow import pair, recipe
from tests.test_production_recovery import branch_approved
from tests.test_workflow_core import configured, fixture_pdf
from tests.test_workflow_data_steps import insert
from tests.test_workflow_production_review import SESSION, receipts
from workflow.batch import BatchRun, approve, execute_batch, prepare
from workflow.engine import execute
from workflow.extraction import ExtractionStore
from workflow.model import WorkflowRun
from workflow.production_review import prepare_contexts, validate_receipts
from workflow.worker import dispatch


def batch_review(tmp_path, *, split=False):
    job = pair(tmp_path, pages=1, records=2)
    spec = recipe([job]).upgraded()
    if split:
        spec = insert(spec, "template", "split_output", {"method": "count", "count": 1})
    run = prepare(spec, BatchRun(jobs=[job]), tmp_path / "work")
    approve(run, [job.id])
    request = dict(operation="batch_run", review_kind="batch", spec=spec.to_dict(), batch=run.to_dict(),
                   directory=str(tmp_path / "work"), output_dir=str(tmp_path / "out"))
    evidence = receipts(request, prepare_contexts(request)["contexts"])
    authorization = validate_receipts({**request, "production_reviews": evidence}, session=SESSION)
    return spec, run, authorization


def pdf_review(tmp_path, *, split=False):
    source = fixture_pdf(tmp_path / "source.pdf")
    spec = configured(source, tmp_path / "out").upgraded()
    if split:
        spec = insert(spec, "group", "split_output", {"method": "count", "count": 1})
    run = execute(spec, WorkflowRun(), tmp_path / "work")
    assert not run.error, run.error
    with ExtractionStore(run.database) as store:
        store.accept()
    run.accepted = True
    request = dict(operation="run", until="output", review_kind="pdf", spec=spec.to_dict(), run=asdict(run),
                   directory=str(tmp_path / "work"), output_dir=str(tmp_path / "out"))
    evidence = receipts(request, prepare_contexts(request)["contexts"])
    return {**request, "production_reviews": evidence}


def test_pdf_worker_rejects_swapped_extraction_database(tmp_path):
    request = pdf_review(tmp_path)
    replacement = tmp_path / "changed-extraction.sqlite"
    shutil.copyfile(request["run"]["database"], replacement)
    with sqlite3.connect(replacement) as db:
        db.execute("UPDATE cells SET value='99999'")
    changed = copy.deepcopy(request)
    changed["run"]["database"] = str(replacement)
    try:
        result = dispatch(changed, lambda *_: None, lambda: False, session=SESSION)
    except CompositionError as exc:
        result = {"error": str(exc)}
    assert result.get("error"), "An unreviewed extraction DB was accepted"
    assert not (tmp_path / "out").exists()


def test_direct_batch_rejects_changed_destination_before_any_write(tmp_path):
    spec, run, authorization = batch_review(tmp_path)
    wrong = tmp_path / "not-approved"
    with pytest.raises(CompositionError):
        execute_batch(spec, run, wrong, authorization=authorization)
    assert not wrong.exists()


def link_to(link, target, *, directory):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError:
        if not directory:
            pytest.skip("Host lacks file-symlink permission; native Mac gate covers this case")
        import subprocess
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if made.returncode:
            pytest.skip("Host does not permit symlinks or junctions")


@pytest.mark.parametrize("directory", [False, True])
def test_batch_report_rejects_link_before_external_write(tmp_path, directory):
    spec, run, authorization = batch_review(tmp_path)
    outside = tmp_path / "outside-approved-root"
    outside.mkdir()
    marker = outside / "keep.csv"
    marker.write_text("untouched", encoding="utf-8")
    root = tmp_path / "out"
    root.mkdir()
    batch = root / ("batch-" + run.batch_id)
    if directory:
        link = batch
        link_to(link, outside, directory=True)
    else:
        batch.mkdir()
        link = batch / "batch-summary.csv"
        link_to(link, marker, directory=False)
    try:
        try:
            execute_batch(spec, run, root, authorization=authorization)
        except (CompositionError, ValueError):
            pass
        assert marker.read_text(encoding="utf-8") == "untouched"
        assert sorted(p.name for p in outside.iterdir()) == ["keep.csv"]
        assert not (batch / "batch.json").exists()
    finally:
        link.unlink() if link.is_symlink() else link.rmdir()


def test_split_batch_replay_skips_composition_after_verified_commit(tmp_path, monkeypatch):
    import workflow.batch as module
    spec, run, authorization = batch_review(tmp_path, split=True)
    original = copy.deepcopy(run)
    first = execute_batch(spec, run, tmp_path / "out", authorization=authorization)
    assert first.status == "Completed", first.jobs[0].error
    published = first.jobs[0].result
    content = {p: p.read_bytes() for p in Path(published["report_dir"]).iterdir() if p.is_file()}
    def unexpected(*args, **kwargs):
        raise RuntimeError("Already committed split job was recomposed")
    monkeypatch.setattr(module, "generate", unexpected)
    replay = execute_batch(spec, original, tmp_path / "out", authorization=authorization)
    assert replay.status == "Completed", replay.jobs[0].error
    assert replay.jobs[0].result["output_pdf"] == published["output_pdf"]
    assert all(p.read_bytes() == value for p, value in content.items())


def test_split_pdf_replay_skips_composition_after_verified_commit(tmp_path, monkeypatch):
    import workflow.pdf_pipeline as module
    request = pdf_review(tmp_path, split=True)
    first = dispatch(copy.deepcopy(request), lambda *_: None, lambda: False, session=SESSION)
    assert not first.get("error"), first
    def unexpected(*args, **kwargs):
        raise RuntimeError("Already committed split PDF workflow was recomposed")
    monkeypatch.setattr(module, "generate", unexpected)
    replay = dispatch(copy.deepcopy(request), lambda *_: None, lambda: False, session=SESSION)
    assert not replay.get("error"), replay
    assert replay["output"]["output_pdf"] == first["output"]["output_pdf"]


def test_recovery_cannot_relabel_old_output_as_changed_template(tmp_path):
    from workflow.branch_engine import branch_signature, execute_routes, prepare_routes, recover_public_run
    spec, run, authorization = branch_approved(tmp_path)
    completed = execute_routes(spec, run, tmp_path / "work", tmp_path / "out", authorization=authorization)
    assert completed["status"] == "Completed"
    root = Path(completed["report_dir"])
    manifest = json.loads((root / "run.json").read_text(encoding="utf-8"))
    target = next(iter(spec.execution_plan().branches.values()))[0]
    template = load_project(target.params["path"])
    template.pages[0].elements.append(Element(value="NEW REQUIRED LAYOUT", y_mm=100))
    save_project(template, target.params["path"])
    affected = [entry for entry in manifest["jobs"] if entry["branch_id"] == manifest["jobs"][0]["branch_id"]]
    for entry in affected:
        entry["signature"] = branch_signature(spec, manifest["signature"], entry["branch_id"])
    (root / "run.json").write_text(json.dumps(manifest), encoding="utf-8")
    recovered = recover_public_run(spec, root)
    checked = prepare_routes(spec, tmp_path / "new-work", previous=recovered)
    assert all(entry["status"] != "Completed" for entry in checked["jobs"] if entry["id"] in {a["id"] for a in affected})
    assert all(Path(entry["result"]["output_pdf"]).is_file() for entry in manifest["jobs"])


def test_split_batch_claim_blocks_another_execution_before_composition(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    import workflow.batch as module
    from composition.production.journal import JobJournal, _binding

    spec, run, authorization = batch_review(tmp_path, split=True)
    identity = authorization.contexts[0]["job"]["job_id"]
    root = Path(authorization.contexts[0]["job"]["output_dir"])
    calls = []
    def unexpected(*args, **kwargs):
        calls.append(True)
        raise RuntimeError("Composition started before its final claim")
    monkeypatch.setattr(module, "generate", unexpected)
    journal = JobJournal(root, identity, _binding(authorization, identity))
    with journal.claim(), ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(execute_batch, spec, run, tmp_path / "out", authorization=authorization).result(timeout=20)
    assert not calls
    assert "already running" in result.jobs[0].error
    assert not journal.final.exists()


def test_completion_report_reference_must_point_to_its_package(tmp_path):
    from composition.production.generator import generate
    from composition.production.journal import _binding, verify_package
    from tests.test_production_recovery import authorized

    job, authorization = authorized(tmp_path)
    result = generate(job, authorization=authorization)
    assert result.status == "completed", result.error
    file = Path(result.report_dir) / "completion.json"
    packet = json.loads(file.read_text(encoding="utf-8"))
    packet["result"]["report_dir"] = str(tmp_path / "unrelated-report")
    file.write_text(json.dumps(packet), encoding="utf-8")
    assert verify_package(result.report_dir, job.job_id, _binding(authorization, job.job_id)) is None
