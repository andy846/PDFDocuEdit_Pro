from __future__ import annotations

import json

import fitz
import pytest

from composition.data.source import import_records
from composition.engine.assets import asset_root
from composition.production.generator import generate, reconcile
from composition.production.model import JobResult, ProductionJob
from composition.template.model import CompositionError, DataConfig, Element, Template

pytestmark = pytest.mark.skipif(
    not (asset_root() / "qpdf" / "qpdf.exe").exists(),
    reason="Windows release production tests require prepared qpdf assets.",
)


def job_for(tmp_path, count=1, values=None, chunk=500):
    source = tmp_path / "data.csv"
    source.write_text("Name\n" + "\n".join(values or [f"Customer {i}" for i in range(count)]) + "\n", encoding="utf-8")
    store = import_records(DataConfig(path=str(source)), tmp_path / "records.db")
    template = Template(elements=[Element(value="Record {{Name}}", height_mm=20)])
    return ProductionJob(template.to_dict(), str(store.path), str(tmp_path / "output"), chunk_size=chunk)


@pytest.mark.parametrize("count", [1, 100, 1000])
def test_production_reconciliation_and_order(tmp_path, count):
    job = job_for(tmp_path, count, chunk=73)
    result = generate(job)
    assert result.status == "completed", result.error
    assert result.input_records == result.processed_records == result.successful_records == count
    assert result.generated_pages == count
    with fitz.open(result.output_pdf) as doc:
        assert doc.page_count == count
        assert "Customer 0" in doc[0].get_text()
        assert f"Customer {count-1}" in doc[-1].get_text()
    log = json.loads((tmp_path / "output" / job.job_id / "job.json").read_text(encoding="utf-8"))
    assert log["source"]["sha256"]
    assert log["status"] == "completed"
    assert (tmp_path / "output" / job.job_id / "control.csv").exists()
    assert not list((tmp_path / "output").glob(".*"))


def test_record_error_publishes_only_diagnostics(tmp_path):
    job = job_for(tmp_path, values=["Customer 1", "\u9999\u6e2f"])
    result = generate(job)
    assert result.status == "failed"
    assert result.error_record == 2
    assert result.failed_records == 1
    assert result.generated_files == 0
    assert not list((tmp_path / "output").rglob("*.pdf"))
    assert (tmp_path / "output" / f"{job.job_id}-failed" / "job.json").exists()


def test_cancellation_and_duplicate_identity(tmp_path):
    job = job_for(tmp_path, 100)
    cancelled = False

    def progress(*args):
        nonlocal cancelled
        cancelled = True

    result = generate(job, progress=progress, is_cancelled=lambda: cancelled)
    assert result.status == "cancelled"
    assert result.generated_files == 0
    assert not list((tmp_path / "output").rglob("*.pdf"))
    with pytest.raises(CompositionError, match="already exists"):
        generate(job)


def test_reconciliation_discrepancy_blocks_publication(tmp_path, monkeypatch):
    job = job_for(tmp_path, 3)
    from composition.production import generator
    original = generator.reconcile

    def mismatch(result):
        result.generated_pages -= 1
        original(result)

    monkeypatch.setattr(generator, "reconcile", mismatch)
    result = generate(job)
    assert result.status == "failed"
    assert "RECONCILIATION FAILED" in result.error
    assert not list((tmp_path / "output").rglob("*.pdf"))


def test_reconcile_rejects_missing_record():
    with pytest.raises(CompositionError, match="RECONCILIATION FAILED"):
        reconcile(JobResult("test", input_records=2, processed_records=1, successful_records=1,
                            generated_pages=1, generated_files=1))


def test_cancel_during_assembler_never_publishes_pdf(tmp_path):
    job = job_for(tmp_path, 100)
    cancelled = False

    def progress(done, total, message):
        nonlocal cancelled
        if message.startswith("Assembling"):
            cancelled = True

    result = generate(job, progress=progress, is_cancelled=lambda: cancelled)
    assert result.status == "cancelled"
    assert result.generated_files == 0
    assert not list((tmp_path / "output").rglob("*.pdf"))


def test_unicode_and_space_output_path(tmp_path):
    job = job_for(tmp_path, 2)
    job.output_dir = str(tmp_path / "\u9999\u6e2f production")
    result = generate(job)
    assert result.status == "completed", result.error
    with fitz.open(result.output_pdf) as doc:
        assert doc.page_count == 2
