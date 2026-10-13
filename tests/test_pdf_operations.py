import json
from dataclasses import replace

import fitz
import pytest

from core.pdf_operations.analysis import PdfCancelled, analyse
from core.pdf_operations.model import PdfOperationError, PdfOptions
from core.pdf_operations.service import execute


def source_file(tmp_path, *, encrypted=False):
    path = tmp_path / "customer.pdf"
    with fitz.open() as doc:
        for _ in range(2):
            page = doc.new_page(width=300, height=400)
            page.insert_text((30, 40), "Searchable customer text")
            page.add_freetext_annot((30, 80, 250, 120), "Filled annotation")
        doc.set_toc([[1, "Customer", 1]])
        doc.set_metadata({"title": "Customer"})
        if encrypted:
            doc.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")
        else:
            doc.save(path)
    return path


def test_flatten_new_copy_partial_pages_audit_and_original_unchanged(tmp_path):
    source = source_file(tmp_path)
    original = source.read_bytes()
    plan = analyse(source, PdfOptions(pages=(0,)))
    assert plan.annotations == 1 and not plan.issues
    result = execute(plan, tmp_path / "output")
    with fitz.open(result["output_pdf"]) as output:
        assert output.page_count == 2
        assert not list(output[0].annots() or [])
        assert len(list(output[1].annots() or [])) == 1
        assert "Searchable customer text" in output[0].get_text()
        assert output.get_toc()[0][1] == "Customer"
        assert output.metadata["title"] == "Customer"
    assert source.read_bytes() == original
    report = json.loads((tmp_path / "output" / result["job_id"] / "job.json").read_text())
    assert report["validation"]["visual_comparison"] == "passed"
    assert report["changes"][0]["objects"] == 1


def test_changed_source_or_cancel_never_publishes(tmp_path):
    source = source_file(tmp_path)
    plan = analyse(source)
    source.write_bytes(source.read_bytes() + b"\n%changed\n")
    with pytest.raises(PdfOperationError, match="changed"):
        execute(plan, tmp_path / "output")
    assert not list((tmp_path / "output").rglob("*.pdf"))
    plan = analyse(source)
    calls = 0

    def cancelled():
        nonlocal calls
        calls += 1
        return calls > 4

    with pytest.raises(PdfCancelled):
        execute(plan, tmp_path / "output", is_cancelled=cancelled)
    assert not list((tmp_path / "output").rglob("*.pdf"))
    assert list((tmp_path / "output").rglob("job.json"))


def test_safe_repair_retains_annotations_text_and_reports_structure(tmp_path):
    source = source_file(tmp_path)
    plan = analyse(source, PdfOptions(operation="repair", annotations=False))
    result = execute(plan, tmp_path / "output")
    with fitz.open(result["output_pdf"]) as output:
        assert len(list(output[0].annots() or [])) == 1
        assert "Searchable customer text" in output[0].get_text()
    assert result["changes"][0]["action"] == "structural_rewrite"


def test_raster_requires_confirmation_and_only_changes_selected_pages(tmp_path):
    source = source_file(tmp_path)
    options = PdfOptions(pages=(0,), rasterise=True, dpi=150)
    with pytest.raises(PdfOperationError, match="Confirm rasterisation"):
        execute(analyse(source, options), tmp_path / "output")
    result = execute(analyse(source, replace(options, acknowledge_raster=True)), tmp_path / "output")
    with fitz.open(result["output_pdf"]) as output:
        assert not output[0].get_text().strip()
        assert "Searchable customer text" in output[1].get_text()
        assert output[0].rect == output[1].rect


def test_encrypted_source_cannot_silently_become_unencrypted(tmp_path):
    source = source_file(tmp_path, encrypted=True)
    plan = analyse(source, password="secret")
    assert plan.encrypted
    with pytest.raises(PdfOperationError, match="output password"):
        execute(plan, tmp_path / "output", password="secret")
    result = execute(plan, tmp_path / "output", password="secret", output_password="secret")
    with fitz.open(result["output_pdf"]) as doc:
        assert doc.needs_pass and doc.authenticate("secret")


def test_failure_leaves_no_final_bundle(tmp_path, monkeypatch):
    source = source_file(tmp_path)
    from core.pdf_operations import service
    monkeypatch.setattr(service, "validate_pdf_file", lambda *a, **k: (_ for _ in ()).throw(ValueError("invalid output")))
    with pytest.raises(ValueError, match="invalid output"):
        execute(analyse(source), tmp_path / "output")
    assert not list((tmp_path / "output").rglob("*.pdf"))
    reports = list((tmp_path / "output").rglob("job.json"))
    assert len(reports) == 1 and json.loads(reports[0].read_text())["published_files"] == 0


@pytest.mark.parametrize("operation", ["flatten", "repair"])
@pytest.mark.parametrize("name", ["source-snapshot.pdf", "candidate.pdf", "preflight.pdf", "recovered-source.pdf"])
def test_output_names_cannot_collide_with_private_work_files(tmp_path, operation, name):
    from pathlib import Path
    source = source_file(tmp_path)
    original = source.read_bytes()
    options = PdfOptions(operation=operation, annotations=operation == "flatten",
                         preflight=name == "preflight.pdf", allow_preflight_errors=True)
    result = execute(analyse(source, options), tmp_path / "output", output_name=name)
    output = Path(result["output_pdf"])
    assert output.name == name and output.is_file()
    with fitz.open(output) as doc:
        assert doc.page_count == 2
        assert "Searchable customer text" in doc[0].get_text()
    assert source.read_bytes() == original
    assert {p.name for p in output.parent.iterdir()} == {name, "job.json", "control.csv"}
