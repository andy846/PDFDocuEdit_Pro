import json
import subprocess
import sys
from pathlib import Path

import pytest

from composition.production.generator import generate
from composition.production.journal import JobJournal, _binding, verify_package
from composition.review.authorization import ProductionAuthorization
from composition.template.model import CompositionError
from tests.test_production_authorization import reviewed


def authorized(tmp_path):
    session, job, receipt = reviewed(tmp_path)
    return job, ProductionAuthorization([receipt], session)


def test_repeat_execution_verifies_and_skips_committed_job(tmp_path, monkeypatch):
    job, auth = authorized(tmp_path)
    first = generate(job, authorization=auth)
    assert first.status == "completed", first.error
    files = {p.relative_to(Path(first.report_dir)).as_posix(): p.read_bytes() for p in Path(first.report_dir).rglob("*") if p.is_file()}
    import composition.production.generator as module
    monkeypatch.setattr(module, "_assemble", lambda *a, **k: pytest.fail("Repeated publication rendered again"))
    repeated = generate(job, authorization=auth)
    assert repeated.output_pdf == first.output_pdf and repeated.status == "completed"
    assert files == {p.relative_to(Path(first.report_dir)).as_posix(): p.read_bytes() for p in Path(first.report_dir).rglob("*") if p.is_file()}


def test_committed_journal_write_failure_preserves_pdf_and_recovers(tmp_path, monkeypatch):
    import composition.production.journal as module
    job, auth = authorized(tmp_path)
    write = module._write
    def fail(path, value):
        if value.get("state") == "Committed":
            raise OSError("injected journal disk failure")
        return write(path, value)
    monkeypatch.setattr(module, "_write", fail)
    first = generate(job, authorization=auth)
    assert first.status == "completed" and Path(first.output_pdf).is_file()
    assert any("write failed" in w for w in first.warnings)
    persisted = Path(job.output_dir, ".production-state", job.job_id + ".json")
    assert json.loads(persisted.read_text())["state"] == "Publishing"
    monkeypatch.setattr(module, "_write", write)
    second = generate(job, authorization=auth)
    assert second.status == "completed" and second.output_pdf == first.output_pdf
    assert json.loads(persisted.read_text())["state"] == "Committed"


def test_exception_immediately_after_rename_does_not_discard_output(tmp_path, monkeypatch):
    import composition.production.journal as module
    job, auth = authorized(tmp_path)
    rename = module.os.rename
    def fail(source, target):
        rename(source, target)
        if Path(target).name == job.job_id:
            raise RuntimeError("injected post-commit failure")
    monkeypatch.setattr(module.os, "rename", fail)
    result = generate(job, authorization=auth)
    assert result.status == "completed" and Path(result.output_pdf).is_file()
    assert any("published and verified" in w for w in result.warnings)


def test_corrupted_committed_artifact_blocks_retry(tmp_path):
    job, auth = authorized(tmp_path)
    result = generate(job, authorization=auth)
    Path(result.report_dir, "control.csv").write_text("changed")
    with pytest.raises(CompositionError, match="cannot be verified"):
        generate(job, authorization=auth)
    assert Path(result.output_pdf).is_file()
    assert verify_package(result.report_dir, job.job_id, _binding(auth, job.job_id)) is None


def test_generation_failure_requires_new_attempt(tmp_path, monkeypatch):
    import composition.production.generator as module
    job, auth = authorized(tmp_path)
    monkeypatch.setattr(module, "_assemble", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("injected assembly failure")))
    result = generate(job, authorization=auth)
    assert result.status == "failed" and not result.output_pdf
    assert not Path(job.output_dir, job.job_id).exists()
    with pytest.raises(CompositionError, match="new output folder"):
        generate(job, authorization=auth)


def test_live_exclusive_claim_rejects_other_process(tmp_path):
    job, auth = authorized(tmp_path)
    journal = JobJournal(job.output_dir, job.job_id, _binding(auth, job.job_id))
    code = "from composition.production.journal import JobJournal; from composition.template.model import CompositionError; import sys; j=JobJournal(sys.argv[1],sys.argv[2],sys.argv[3]); "
    code += "\ntry:\n with j.claim(): pass\nexcept CompositionError as e:\n print(e); sys.exit(7)"
    with journal.claim():
        child = subprocess.run([sys.executable, "-c", code, job.output_dir, job.job_id, journal.binding], capture_output=True, text=True)
        assert child.returncode == 7 and "already running" in child.stdout


def test_interrupted_scratch_quarantined_without_publication(tmp_path):
    job, auth = authorized(tmp_path)
    journal = JobJournal(job.output_dir, job.job_id, _binding(auth, job.job_id))
    with journal.claim():
        staging = Path(job.output_dir, "." + job.job_id + "-unfinished")
        staging.mkdir()
        (staging / "partial.pdf").write_bytes(b"incomplete")
    with pytest.raises(CompositionError, match="new output folder"):
        generate(job, authorization=auth)
    assert not Path(job.output_dir, job.job_id).exists()
    assert not staging.exists()
    assert list(Path(job.output_dir, ".quarantine").rglob("partial.pdf"))


def test_progress_observer_failure_does_not_cancel_production(tmp_path):
    job, auth = authorized(tmp_path)
    def fail(*_):
        raise RuntimeError("injected notification failure")
    result = generate(job, authorization=auth, progress=fail)
    assert result.status == "completed" and Path(result.output_pdf).is_file()
    assert any("notification failed" in w for w in result.warnings)


def branch_approved(tmp_path):
    from tests.test_workflow_branch_engine import fixture
    from tests.test_workflow_production_review import SESSION, receipts
    from workflow.branch_engine import approve_routes, prepare_routes
    from workflow.production_review import prepare_contexts, validate_receipts
    spec = fixture(tmp_path, records=2)
    run = prepare_routes(spec, tmp_path / "work")
    approve_routes(spec, run, [j["id"] for j in run["jobs"]])
    request = dict(operation="branch_run", review_kind="branch", directory=str(tmp_path / "work"), output_dir=str(tmp_path / "out"), spec=spec.to_dict(), run=run)
    evidence = receipts(request, prepare_contexts(request)["contexts"])
    auth = validate_receipts({**request, "production_reviews": evidence}, session=SESSION)
    return spec, run, auth


def test_branch_unexpected_failure_persisted_and_approvals_revoked(tmp_path, monkeypatch):
    import workflow.branch_engine as module
    spec, run, auth = branch_approved(tmp_path)
    monkeypatch.setattr(module, "execute_batch", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("injected branch failure")))
    result = module.execute_routes(spec, run, tmp_path / "work", tmp_path / "out", authorization=auth)
    assert result["status"] == "Failed" and "injected branch failure" in result["error"]
    assert not any(j["approved"] or j["status"] == "Running" for j in result["jobs"])
    persisted = json.loads(Path(result["directory"], "run.json").read_text())
    assert persisted["status"] == "Failed"


def test_later_branch_failure_preserves_committed_first_job(tmp_path, monkeypatch):
    import workflow.branch_engine as module
    spec, run, auth = branch_approved(tmp_path)
    execute = module.execute_batch
    calls = 0
    def fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected second branch failure")
        return execute(*args, **kwargs)
    monkeypatch.setattr(module, "execute_batch", fail)
    result = module.execute_routes(spec, run, tmp_path / "work", tmp_path / "out", authorization=auth)
    assert result["status"] == "Partial / needs attention"
    first = result["jobs"][0]["batch"]["jobs"][0]["result"]
    assert Path(first["output_pdf"]).is_file()
    assert not any(j["approved"] for j in result["jobs"])


def test_branch_report_failure_retains_all_completed_output(tmp_path, monkeypatch):
    import workflow.branch_engine as module
    spec, run, auth = branch_approved(tmp_path)
    monkeypatch.setattr(module, "export_results", lambda *a: (_ for _ in ()).throw(OSError("injected report failure")))
    result = module.execute_routes(spec, run, tmp_path / "work", tmp_path / "out", authorization=auth)
    assert result["status"] == "Completed with report warnings" and result["report_error"]
    assert all(j["status"] == "Completed" for j in result["jobs"])


def test_recover_after_workspace_is_lost_verifies_outputs_and_rechecks(tmp_path):
    import shutil

    from workflow.branch_engine import execute_routes, prepare_routes, recover_public_run
    spec, run, auth = branch_approved(tmp_path)
    result = execute_routes(spec, run, tmp_path / "work", tmp_path / "out", authorization=auth)
    assert result["status"] == "Completed"
    folder = Path(result["report_dir"])
    pdfs = list(folder.rglob("*.pdf"))
    content = {str(p): p.read_bytes() for p in pdfs}
    shutil.rmtree(tmp_path / "work")
    recovered = recover_public_run(spec, folder)
    assert recovered["status"] == "Completed"
    assert all(not j["approved"] for j in recovered["jobs"])
    checked = prepare_routes(spec, tmp_path / "new-work", previous=recovered)
    assert all(j["status"] == "Completed" for j in checked["jobs"])
    assert content == {str(p): p.read_bytes() for p in pdfs}


def test_branch_acknowledgement_tampering_rejected_before_output(tmp_path):
    from workflow.branch_engine import execute_routes
    spec, run, auth = branch_approved(tmp_path)
    run["acknowledged"] = not run["acknowledged"]
    with pytest.raises(CompositionError, match="acknowledgement changed"):
        execute_routes(spec, run, tmp_path / "work", tmp_path / "out", authorization=auth)
    assert not (tmp_path / "out").exists()
