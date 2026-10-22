"""The engine-only adapter must neutralize new extraction defaults once."""
import subprocess
import sys
from pathlib import Path

import pytest


def test_backend_preserves_native_types_and_legacy_extraction_settings():
    import pymupdf

    from core.pdf_backend import fitz
    assert fitz is pymupdf
    assert not fitz.TOOLS.unset_quad_corrections()
    assert fitz._get_layout is None
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 50), "backend contract")
        assert page.get_text().strip() == "backend contract"
        assert isinstance(page.rect, fitz.Rect)


def test_backend_is_headless_and_does_not_load_editor_or_qt():
    result = subprocess.run([sys.executable, "-c",
        "from core.pdf_backend import fitz; import sys; "
        "assert not any(k.startswith('PyQt6') for k in sys.modules); "
        "assert 'core.viewer' not in sys.modules; "
        "assert not fitz.TOOLS.unset_quad_corrections(); assert fitz._get_layout is None"],
        capture_output=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_windows_qt_first_never_crosses_into_unsafe_native_import():
    from core.pdf_backend import fitz
    result = subprocess.run([sys.executable, "-X", "faulthandler", "-c",
        "from PyQt6.QtCore import QObject; from core.pdf_backend import fitz"],
        capture_output=True, encoding="utf-8", timeout=20)
    if sys.platform == "win32" and fitz.VersionBind.split(".")[0] == "2":
        assert result.returncode == 1 and "before Qt" in result.stderr
    else:
        assert result.returncode == 0, result.stderr


def test_entry_authorizes_workers_before_loading_native_backend():
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert source.index("require_worker_access()") < source.index("from core.pdf_backend") < source.index("from PyQt6")


def test_standalone_canvas_benchmark_initializes_engine_before_qt():
    result = subprocess.run([sys.executable, "-c", "import scripts.benchmark_canvas"],
                            capture_output=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("script", ["workflow_benchmark.py", "benchmark_pdf_overlay.py"])
def test_direct_benchmark_entry_resolves_project_modules(script):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / "scripts" / script), "--help"],
                            cwd=root, capture_output=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0 and "usage:" in result.stdout, result.stdout + result.stderr


def test_existing_pdf2docx_export_preserves_real_text_and_source(tmp_path):
    import hashlib

    from docx import Document

    from core.pdf_backend import fitz
    from core.tools import convert_pdf_to_word

    source, target = tmp_path / "source.pdf", tmp_path / "output.docx"
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 100), "PDF backend conversion contract", fontsize=12)
        doc.save(source)
    before = hashlib.sha256(source.read_bytes()).digest()
    assert convert_pdf_to_word(source, target) == target
    assert "PDF backend conversion contract" in "\n".join(p.text for p in Document(target).paragraphs)
    assert hashlib.sha256(source.read_bytes()).digest() == before
    assert not list(tmp_path.glob(".output-*.docx"))
