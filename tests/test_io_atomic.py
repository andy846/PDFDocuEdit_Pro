from pathlib import Path

import fitz
import pytest

import core.annotation_io as annotation_io
import core.io_atomic as io_atomic
import core.pdf_engine as pdf_engine
from core.io_atomic import atomic_output


@pytest.mark.parametrize("failure", ["write", "validation", "replace"])
def test_failed_staged_output_preserves_destination(tmp_path, monkeypatch, failure):
    target = tmp_path / "existing.pdf"
    target.write_bytes(b"original")
    if failure == "replace":
        def fail_replace(*args):
            raise OSError("destination locked")
        monkeypatch.setattr(io_atomic.os, "replace", fail_replace)
    with pytest.raises((OSError, ValueError)):
        with atomic_output(target) as staged:
            assert staged.parent == target.parent
            staged.write_bytes(b"partial" if failure == "write" else b"complete")
            if failure == "write":
                raise OSError("disk full")
            if failure == "validation":
                raise ValueError("invalid result")
    assert target.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [target]


def test_staged_output_commits_only_after_scope(tmp_path):
    target = tmp_path / "nested" / "result.json"
    with atomic_output(target) as staged:
        staged.write_text('{"ok": true}')
        assert not target.exists()
    assert target.read_text() == '{"ok": true}'
    assert not staged.exists()


@pytest.mark.parametrize("export", ["export_annotations_json", "export_annotation_summary"])
def test_annotation_export_partial_write_keeps_old_file(tmp_path, monkeypatch, export):
    target = tmp_path / "existing.txt"
    target.write_text("old report")
    write = Path.write_text
    def fail_write(path, *args, **kwargs):
        write(path, "partial output")
        raise OSError("disk full")
    monkeypatch.setattr(Path, "write_text", fail_write)
    with fitz.open() as doc:
        doc.new_page().add_text_annot((72, 72), "Note")
        with pytest.raises(OSError):
            getattr(annotation_io, export)(doc, target)
    assert target.read_text() == "old report"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("operation", ["extract", "flatten"])
def test_pdf_output_validation_precedes_replacement(tmp_path, monkeypatch, operation):
    source = tmp_path / "source.pdf"
    target = tmp_path / "existing.pdf"
    target.write_bytes(b"original output")
    with fitz.open() as doc:
        doc.new_page().add_text_annot((72, 72), "Note")
        doc.save(source)
    engine = pdf_engine.PdfEngine()
    engine.open(source)
    def fail_validation(*args, **kwargs):
        raise ValueError("invalid generated PDF")
    module = pdf_engine if operation == "extract" else annotation_io
    monkeypatch.setattr(module, "validate_pdf_file", fail_validation)
    try:
        with pytest.raises(ValueError):
            if operation == "extract":
                engine.extract_pages([0], target)
            else:
                annotation_io.flatten_annotations(engine.document, target)
        assert target.read_bytes() == b"original output"
        assert set(tmp_path.iterdir()) == {source, target}
    finally:
        engine.close()
