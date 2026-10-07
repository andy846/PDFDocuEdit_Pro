"""Generated structural and destructive-option fixtures, not external customer PDFs."""
import re
from dataclasses import replace
from pathlib import Path

import fitz
import pytest

from core.pdf_operations.analysis import analyse
from core.pdf_operations.model import PdfOperationError, PdfOptions
from core.pdf_operations.service import execute
from tests.test_pdf_operations import source_file


def test_normalise_removes_only_requested_attachments_and_metadata(tmp_path):
    path = tmp_path / "attachments.pdf"
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 40), "Searchable original")
        page.add_rect_annot((50, 60, 160, 90))
        doc.embfile_add("sample.txt", b"attachment data")
        doc.set_metadata({"title": "Preserved title"})
        doc.set_xml_metadata("<metadata>original</metadata>")
        doc.save(path)
    options = PdfOptions(operation="repair", mode="normalise", annotations=False, remove_attachments=True)
    result = execute(analyse(path, options), tmp_path / "out")
    with fitz.open(result["output_pdf"]) as output:
        assert output.embfile_count() == 0
        assert output.metadata["title"] == "Preserved title"
        assert len(list(output[0].annots() or [])) == 1
    removed = execute(analyse(path, replace(options, remove_metadata=True)), tmp_path / "out")
    with fitz.open(removed["output_pdf"]) as output:
        assert not output.metadata["title"] and not output.get_xml_metadata()
        assert "Searchable original" in output[0].get_text()


def test_rebuilds_recoverable_xref_and_retains_incremental_content(tmp_path):
    source = source_file(tmp_path)
    with fitz.open(source) as doc:
        doc[0].insert_text((30, 170), "Incremental update")
        doc.saveIncr()
    broken = tmp_path / "broken-xref.pdf"
    broken.write_bytes(re.sub(rb"startxref\s+\d+", b"startxref\n1", source.read_bytes()))
    raw = broken.read_bytes()
    plan = analyse(broken, PdfOptions(operation="repair", annotations=False))
    assert plan.diagnostics["structure"]["opened_with_repair"]
    result = execute(plan, tmp_path / "out")
    with fitz.open(result["output_pdf"]) as output:
        assert not output.is_repaired
        assert "Incremental update" in output[0].get_text()
    assert broken.read_bytes() == raw and result["structure_after"]["status"] == "OK"


def test_signed_widget_requires_acknowledgement_without_claiming_signature_verification(tmp_path):
    path = tmp_path / "signature-marker.pdf"
    with fitz.open() as doc:
        page = doc.new_page()
        widget = fitz.Widget()
        widget.field_name = "Signature"
        widget.field_type = fitz.PDF_WIDGET_TYPE_SIGNATURE
        widget.rect = fitz.Rect(40, 60, 180, 100)
        added = page.add_widget(widget)
        # A structural signature marker, deliberately NOT a valid signed fixture.
        signature = doc.get_new_xref()
        doc.update_object(signature, "<< /Type /Sig /ByteRange [0 0 0 0] /Contents <00> >>")
        doc.xref_set_key(added.xref, "V", f"{signature} 0 R")
        doc.save(path)
    plan = analyse(path, PdfOptions(operation="repair", annotations=False))
    assert plan.signed
    with pytest.raises(PdfOperationError, match="signature validity"):
        execute(plan, tmp_path / "out")
    assert not list((tmp_path / "out").rglob("*.pdf"))


def test_preflight_before_after_reuses_existing_service(tmp_path):
    path = source_file(tmp_path)
    options = PdfOptions(operation="repair", annotations=False, preflight=True, allow_preflight_errors=True)
    result = execute(analyse(path, options), tmp_path / "out")
    assert result["preflight_before"] is not None and result["preflight_after"] is not None
    assert Path(result["report_dir"], "job.json").is_file()
