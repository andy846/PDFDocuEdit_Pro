"""Frozen QA generation must use the genuine reviewed production contract."""
from pathlib import Path

from composition.production.model import ProductionJob
from composition.review.authorization import ReviewSession
from composition.template.model import Element, Template
from composition.worker import dispatch


def test_frozen_qa_generation_requires_signed_review_and_keeps_secret_private(tmp_path):
    from scripts.macos_smoke import generate_checked_fixture

    session = ReviewSession.new()
    tasks = []
    requests = []
    def worker(request):
        tasks.append(request["task"])
        requests.append(request)
        return dispatch(request, session=session)
    job = ProductionJob(Template(elements=[Element(value="Native acceptance")], record_mode="generated", generated_count=2).to_dict(), "", str(tmp_path / "output"))
    result = generate_checked_fixture(worker, job, tmp_path / "review")
    assert tasks == ["production_review_check", "production_review_approve", "generate"]
    assert result["status"] == "completed"
    assert result["generated_pages"] == 2
    assert Path(result["output_pdf"]).is_file()
    assert requests[-1]["production_review"]["authorization"]["kind"] == "approval"
    assert session.private_payload()["key"] not in repr(requests)
