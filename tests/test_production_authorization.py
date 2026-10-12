import copy
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from composition.production.generator import generate
from composition.production.model import ProductionJob
from composition.review.authorization import ProductionAuthorization, ReviewSession, approve_snapshot
from composition.review.service import create_review
from composition.template.model import CompositionError, Element, Template
from composition.worker import dispatch


def reviewed(tmp_path, *, clock=None):
    session = ReviewSession.new(**({"clock": clock} if clock else {}))
    job = ProductionJob(Template(elements=[Element(value="Checked")], record_mode="generated", generated_count=2).to_dict(), "", str(tmp_path / "out"))
    context = {"kind": "template", "job": asdict(job)}
    result = create_review(tmp_path / "work", context, session=session)
    assert result["status"] == "checked", result["issues"]
    context = result["context"]
    job = ProductionJob(**context["job"])
    receipt = {"directory": str(tmp_path / "work"), "snapshot_id": result["snapshot_id"], "context": context, "acknowledge": True}
    receipt["authorization"] = approve_snapshot(receipt["directory"], receipt["snapshot_id"], context, session=session, acknowledge=True)
    return session, job, receipt


def test_engine_and_worker_fail_closed_without_approval(tmp_path):
    job = ProductionJob(Template(record_mode="generated").to_dict(), "", str(tmp_path / "out"))
    with pytest.raises(CompositionError, match="confirm production"):
        generate(job)
    with pytest.raises(CompositionError, match="confirm production"):
        dispatch({"task": "generate", "job": asdict(job)})
    assert not (tmp_path / "out").exists()


def test_authentic_review_generates_and_altered_job_is_rejected(tmp_path):
    session, job, receipt = reviewed(tmp_path)
    authorization = ProductionAuthorization([receipt], session)
    changed = copy.deepcopy(job)
    changed.output_dir = str(tmp_path / "different")
    with pytest.raises(CompositionError, match="differs"):
        generate(changed, authorization=authorization)
    assert not Path(changed.output_dir).exists()
    result = generate(job, authorization=authorization)
    assert result.status == "completed", result.error
    assert result.generated_pages == 2


@pytest.mark.parametrize("field", ["context", "acknowledge", "snapshot_id", "authorization"])
def test_tampered_receipts_rejected(tmp_path, field):
    session, job, receipt = reviewed(tmp_path)
    changed = copy.deepcopy(receipt)
    if field == "context":
        changed[field]["job"]["output_name"] = "tampered.pdf"
    elif field == "acknowledge":
        changed[field] = False
    elif field == "snapshot_id":
        changed[field] = "a" * 32
    else:
        changed[field]["expires"] += 100000
    with pytest.raises(CompositionError):
        ProductionAuthorization([changed], session)
    assert not Path(job.output_dir).exists()


def test_restart_and_expired_approval_rejected(tmp_path):
    now = [1000.0]
    session, _, receipt = reviewed(tmp_path, clock=lambda: now[0])
    with pytest.raises(CompositionError, match="previous session"):
        ProductionAuthorization([receipt], ReviewSession.new())
    now[0] += 24 * 60 * 60 + 1
    with pytest.raises(CompositionError, match="expired"):
        ProductionAuthorization([receipt], session)


@pytest.mark.parametrize("target", ["snapshot.json", "rows.sqlite"])
def test_tampered_checked_files_rejected(tmp_path, target):
    session, _, receipt = reviewed(tmp_path)
    file = Path(receipt["directory"], "production-review", receipt["snapshot_id"], target)
    if target.endswith("json"):
        value = json.loads(file.read_text())
        value["issues"] = []
        value["summary"]["pages"] += 1
        file.write_text(json.dumps(value))
    else:
        with file.open("ab") as stream:
            stream.write(b"tampering")
    with pytest.raises(CompositionError, match="altered"):
        ProductionAuthorization([receipt], session)


def test_started_job_does_not_expire_mid_generation(tmp_path):
    now = [1000.0]
    session, job, receipt = reviewed(tmp_path, clock=lambda: now[0])
    authorization = ProductionAuthorization([receipt], session)
    authorization.require_job("template", job)
    now[0] += 100000
    authorization.validate()


def test_preview_does_not_require_production_approval(tmp_path):
    response = dispatch({"task": "preview", "template": Template().to_dict(), "target": str(tmp_path / "preview.pdf")})
    assert Path(response["pdf"]).is_file()


@pytest.mark.parametrize("operation", ["branch_run", "batch_run", "run"])
def test_workflow_worker_missing_receipt_never_reaches_production(tmp_path, operation):
    from workflow.worker import dispatch as workflow_dispatch
    request = {"operation": operation, "until": "output", "output_dir": str(tmp_path / "out")}
    with pytest.raises(CompositionError, match="confirm production"):
        workflow_dispatch(request, None, None)
    assert not (tmp_path / "out").exists()


def test_private_worker_key_never_appears_in_request_file(qt_application, tmp_path, monkeypatch):
    from PyQt6.QtCore import QProcess

    from composition.designer.process import Worker, approval_session
    monkeypatch.setattr(QProcess, "start", lambda *args: None)
    worker = Worker(tmp_path, {"task": "production_review_check"})
    try:
        text = worker.request_file.read_text()
        assert approval_session().private_payload()["key"] not in text
        assert "production_session" not in text
        assert json.loads(text)["stdin_secrets"] is True
    finally:
        worker.poll.stop()
        worker.request_file.unlink()
        worker.deleteLater()


def test_windowed_worker_private_approval_channel(qt_application, tmp_path, monkeypatch):
    import sys

    from composition.designer.process import Worker
    from tests.composition.test_designer_controls import wait
    windowed = Path(sys.executable).with_name("pythonw.exe")
    if not windowed.exists():
        pytest.skip("Windowed Windows runtime unavailable")
    job = ProductionJob(Template(record_mode="generated").to_dict(), "", str(tmp_path / "out"))
    context = {"kind": "template", "job": asdict(job)}
    monkeypatch.setattr(sys, "executable", str(windowed))
    worker = Worker(tmp_path, {"task": "production_review_check", "directory": str(tmp_path), "context": context})
    results, errors, ended = [], [], []
    worker.ended.connect(lambda: ended.append(True))
    worker.resultReady.connect(results.append)
    worker.failed.connect(errors.append)
    wait(lambda: bool(results or errors))
    assert not errors, errors
    assert results[0]["status"] == "checked"
    wait(lambda: bool(ended))


def test_changed_headless_external_values_cannot_publish(tmp_path):
    from composition.engine.barcode_profiles import BarcodeProfile
    from composition.engine.generic_layout import BarcodeSegment
    from composition.overlay.generator import generate as overlay_engine
    from composition.overlay.model import EnvelopeSpec, OverlayJob, OverlayObject
    from composition.pdf_source.model import EnvelopeSettings
    from composition.pdf_source.source import inspect_source
    from tests.composition.test_pdf_overlay_models import make_source
    source = make_source(tmp_path / "source.pdf", 2)
    settings = EnvelopeSettings(pages_per_envelope=1)
    profile = BarcodeProfile.fixed_layout(4, [BarcodeSegment(name="Customer", length=4, source="data", value="Account")])
    project = EnvelopeSpec(inspect_source(source, settings), settings,
        [OverlayObject(Element(type="i25", width_mm=90, height_mm=14), profile=profile)], external_fields=["Account"])
    job = OverlayJob(project.to_dict(), str(tmp_path / "output"))
    value = ["0001"]
    def provider(page):
        return {"Account": value[0]}
    session = ReviewSession.new()
    context = {"kind":"overlay", "job":asdict(job)}
    result = create_review(tmp_path / "work", context, session=session, external_values=provider)
    assert result["status"] == "checked", result["issues"]
    receipt = {"directory":str(tmp_path / "work"), "snapshot_id":result["snapshot_id"], "context":result["context"], "acknowledge":True}
    receipt["authorization"] = approve_snapshot(receipt["directory"], receipt["snapshot_id"], receipt["context"], session=session, acknowledge=True)
    value[0] = "0002"
    output = overlay_engine(job, authorization=ProductionAuthorization([receipt], session), external_values=provider)
    assert output.status == "failed" and "changed after review" in output.error
    assert not Path(job.output_dir, job.job_id).exists()
