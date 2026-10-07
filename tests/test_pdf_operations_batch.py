from pathlib import Path

import fitz
import pytest

from core.pdf_operations.batch import analyse_batch, execute_batch
from core.pdf_operations.model import PdfOptions
from core.variables import VariableError


def pdf(path):
    with fitz.open() as doc:
        doc.new_page().add_text_annot((50, 50), "Note")
        doc.save(path)
    return str(path)


def test_batch_preserves_good_output_and_logs_failed_source(tmp_path):
    good = pdf(tmp_path / "good.pdf")
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a PDF")
    analyses = analyse_batch([good, str(bad)], PdfOptions())
    assert analyses[0]["plan"] and analyses[1]["error"]
    result = execute_batch(analyses, tmp_path / "output", "{{input.stem}}_flattened.pdf")
    assert [r["status"] for r in result["files"]] == ["completed", "failed"]
    assert Path(result["files"][0]["output_pdf"]).is_file()
    assert (Path(result["report_dir"]) / "0002-failed.json").is_file()


def test_batch_checks_collisions_before_any_output(tmp_path):
    files = [pdf(tmp_path / "a.pdf"), pdf(tmp_path / "b.pdf")]
    analyses = analyse_batch(files, PdfOptions())
    with pytest.raises(VariableError, match="Duplicate"):
        execute_batch(analyses, tmp_path / "output", "fixed.pdf")
    assert not (tmp_path / "output").exists()
