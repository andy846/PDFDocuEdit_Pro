import copy
from dataclasses import asdict
from pathlib import Path

import fitz
import pytest

from composition.review.service import create_review, review_rows
from composition.template.model import CompositionError
from tests.test_mail_merge_workflow import pair, recipe
from tests.test_workflow_branch_engine import fixture
from tests.test_workflow_core import configured, fixture_pdf
from tests.test_workflow_data_steps import insert
from workflow.batch import BatchRun, approve, prepare
from workflow.branch_engine import approve_routes, prepare_routes
from workflow.engine import execute
from workflow.extraction import ExtractionStore
from workflow.model import WorkflowRun
from workflow.production_review import prepare_contexts, validate_receipts
from workflow.worker import dispatch


def receipts(request, contexts):
    results = [create_review(request["directory"], c) for c in contexts]
    assert all(r["status"] == "checked" for r in results), [r["issues"] for r in results]
    return [{"directory": request["directory"], "snapshot_id": r["snapshot_id"],
             "context": r["context"], "acknowledge": True} for r in results]


def test_batch_review_uses_prepared_identity_and_checks_all_selected_jobs(tmp_path):
    jobs = [pair(tmp_path, "First", records=3), pair(tmp_path, "Second", records=2)]
    spec = recipe(jobs)
    batch = prepare(spec, BatchRun(jobs=jobs), tmp_path / "work")
    approve(batch, [j.id for j in jobs])
    request = {"spec": spec.to_dict(), "batch": batch.to_dict(), "directory": str(tmp_path / "work"),
               "output_dir": str(tmp_path / "out"), "review_kind": "batch", "operation": "batch_run", "approved": [j.id for j in jobs]}
    contexts = prepare_contexts(request)["contexts"]
    reviews = receipts(request, contexts)
    assert not (tmp_path / "out").exists()
    validate_receipts({**request, "production_reviews": reviews})
    with pytest.raises(CompositionError, match="selection"):
        validate_receipts({**request, "production_reviews": reviews[:1]})
    changed = copy.deepcopy(request)
    changed["batch"]["jobs"][0]["sequence_starts"] = {"Seq": 31}
    with pytest.raises(CompositionError, match="settings"):
        validate_receipts({**changed, "production_reviews": reviews})
    result = dispatch({**request, "production_reviews": reviews}, lambda *_: None, lambda: False)
    assert result["batch"]["status"] == "Completed", result
    for job, receipt in zip(result["batch"]["jobs"], reviews, strict=True):
        assert job["result"]["job_id"] == receipt["context"]["job"]["job_id"]
        assert Path(job["result"]["output_pdf"]).is_file()


def test_branch_review_does_not_approve_and_handles_all_template_routes(tmp_path):
    spec = fixture(tmp_path)
    run = prepare_routes(spec, tmp_path / "work")
    request = {"spec": spec.to_dict(), "run": run, "directory": str(tmp_path / "work"),
               "output_dir": str(tmp_path / "out"), "review_kind": "branch", "operation": "branch_run"}
    assert prepare_contexts(request)["contexts"] == []
    approve_routes(spec, run, [j["id"] for j in run["jobs"]])
    contexts = prepare_contexts(request)["contexts"]
    assert len(contexts) == 6
    reviews = receipts(request, contexts)
    validate_receipts({**request, "production_reviews": reviews})
    assert not (tmp_path / "out").exists()
    result = dispatch({**request, "production_reviews": reviews}, lambda *_: None, lambda: False)
    assert result["run"]["status"] == "Completed", result
    assert result["run"]["published_records"] == 12


def test_pdf_filter_review_reuses_checked_data_and_frozen_job_context(tmp_path):
    source = fixture_pdf(tmp_path / "source.pdf")
    spec = insert(configured(source, tmp_path / "out").upgraded(), "group", "filter_records",
                  {"mode": "all", "conditions": [{"field": "Account_No", "operator": "eq", "data_type": "text", "value": "00002"}]})
    run = execute(spec, WorkflowRun(), tmp_path / "work")
    assert not run.error, run.error
    with ExtractionStore(run.database) as store:
        store.accept()
    run.accepted = True
    request = {"spec": spec.to_dict(), "run": asdict(run), "directory": str(tmp_path / "work"),
               "output_dir": str(tmp_path / "out"), "review_kind": "pdf", "operation": "run", "until": "output"}
    contexts = prepare_contexts(request)["contexts"]
    reviews = receipts(request, contexts)
    rows = review_rows(tmp_path / "work", reviews[0]["snapshot_id"], envelope=1)
    assert rows["rows"][0]["source_record"] == 2
    assert review_rows(tmp_path / "work", reviews[0]["snapshot_id"], search="00002")["total"] == 1
    assert rows["pages"][0]["source_file"] == str(source)
    assert rows["pages"][0]["original_page"] == 4
    assert not (tmp_path / "out").exists()
    result = dispatch({**request, "production_reviews": reviews}, lambda *_: None, lambda: False)
    assert not result["error"], result
    output = result["output"]
    assert output["job_id"] == contexts[0]["job"]["job_id"]
    assert output["excluded_envelopes"] == 1
    with fitz.open(output["output_pdf"]) as doc:
        assert len(doc) == 3 and "00002" in doc[0].get_text()
