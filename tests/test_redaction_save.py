from pathlib import Path

import fitz
import pytest

from core.annotations import apply_redaction_marks, redact
from core.pdf_engine import PdfEngine, PdfEngineError

MARKER = "REDACT_PRIVATE_MARKER_74291"


def assert_removed(path: Path, password: str | None = None):
    with fitz.open(path) as doc:
        if password:
            assert doc.needs_pass
            assert doc.authenticate(password)
        assert MARKER not in doc[0].get_text()
        assert "Keep this text" in doc[0].get_text()
        for xref in range(1, doc.xref_length()):
            if doc.xref_is_stream(xref):
                data = doc.xref_stream(xref) or b""
                assert MARKER.encode() not in data
                assert MARKER.encode().hex().encode() not in data.lower()
    if not password:
        data = path.read_bytes()
        assert MARKER.encode() not in data
        assert MARKER.encode().hex().encode() not in data.lower()


@pytest.mark.parametrize("encrypted", [False, True])
def test_redacted_saves_remove_old_streams_including_repeat_save(tmp_path, encrypted):
    source = tmp_path / "source.pdf"
    password = "redaction-test" if encrypted else None
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 96), MARKER)
        page.insert_text((72, 200), "Keep this text")
        options = ({"encryption": fitz.PDF_ENCRYPT_AES_256,
                    "user_pw": password, "owner_pw": "owner-test"} if encrypted else {})
        doc.save(source, **options)
    engine = PdfEngine()
    engine.open(source, password)
    try:
        with engine.mutation_transaction("Redact"):
            redact(engine.document, 0, [fitz.Rect(60, 70, 450, 115)])
            assert apply_redaction_marks(engine.document) == 1
            engine.mark_modified(requires_sanitized_save=True)
        for name in ["first.pdf", "second.pdf"]:
            output = engine.save(tmp_path / name)
            assert_removed(output, password)
            assert engine._requires_sanitized_save
    finally:
        engine.close()


def test_failed_redaction_restores_save_requirement(tmp_path):
    source = tmp_path / "source.pdf"
    with fitz.open() as doc:
        doc.new_page().insert_text((72, 96), MARKER)
        doc.save(source)
    engine = PdfEngine()
    engine.open(source)
    try:
        with pytest.raises(PdfEngineError, match="restored"):
            with engine.mutation_transaction("Failed redaction"):
                redact(engine.document, 0, [fitz.Rect(60, 70, 450, 115)])
                apply_redaction_marks(engine.document)
                engine.mark_modified(requires_sanitized_save=True)
                raise RuntimeError("failure after applying")
        assert not engine._requires_sanitized_save
        assert not engine._requires_full_save
        assert not engine.is_modified
        assert MARKER in engine.document[0].get_text()
    finally:
        engine.close()
