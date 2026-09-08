from __future__ import annotations

from pathlib import Path

import fitz
import pytest

import core.ocr as ocr_module
from core.ocr import OCRError, OCRMode, OCRRequest, run_ocr
from core.platform_service import ProcessResult
from core.tasks import TaskCancelled


def make_pdf(path: Path, pages: int = 2) -> Path:
    with fitz.open() as document:
        for index in range(pages):
            page = document.new_page(width=595, height=842)
            page.draw_rect(fitz.Rect(40, 40, 555, 802), color=(0, 0, 0))
            page.insert_text((72, 100), f"Original {index + 1}")
        document.save(path)
    return path


def fake_runtime(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "tesseract.exe"
    tessdata = tmp_path / "tessdata"
    executable.write_bytes(b"fake")
    tessdata.mkdir()
    monkeypatch.setattr(
        ocr_module,
        "bundled_tesseract_runtime",
        lambda: (executable, tessdata, ""),
    )


def fake_tesseract(command, **_kwargs) -> ProcessResult:
    output = Path(command[2])
    if command[-1] == "txt":
        output.with_suffix(".txt").write_text("繁體中文 English\n", encoding="utf-8")
    else:
        with fitz.open() as layer:
            page = layer.new_page(width=595, height=842)
            page.insert_text((72, 100), "SEARCHABLE OCR TEXT")
            layer.save(output.with_suffix(".pdf"))
    return ProcessResult(0, "", "")


def test_extract_text_utf8_selected_pages_and_atomic_output(tmp_path, monkeypatch) -> None:
    fake_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(ocr_module.PlatformService, "run_cancellable", fake_tesseract)
    source = make_pdf(tmp_path / "來源 文件.pdf", pages=3)
    original = source.read_bytes()
    output = tmp_path / "輸出_OCR.txt"
    progress: list[tuple[int, int, str]] = []

    result = run_ocr(
        OCRRequest(
            str(source),
            (0, 2),
            OCRMode.EXTRACT_TEXT,
            output_path=str(output),
        ),
        progress=lambda current, total, message: progress.append(
            (current, total, message)
        ),
    )

    assert result.pages == (0, 2)
    assert "===== Page 1 =====" in result.text
    assert "===== Page 3 =====" in result.text
    assert "繁體中文 English" in output.read_text(encoding="utf-8")
    assert source.read_bytes() == original
    assert progress[-1][:2] == (2, 2)
    assert not list(tmp_path.glob(".*-*.txt"))


def test_searchable_pdf_keeps_unselected_pages_and_source(tmp_path, monkeypatch) -> None:
    fake_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(ocr_module.PlatformService, "run_cancellable", fake_tesseract)
    source = make_pdf(tmp_path / "scan.pdf", pages=2)
    original = source.read_bytes()
    output = tmp_path / "scan_OCR.pdf"

    result = run_ocr(
        OCRRequest(
            str(source),
            (1,),
            OCRMode.SEARCHABLE_PDF,
            output_path=str(output),
        )
    )

    assert result.output_path == str(output.resolve())
    assert source.read_bytes() == original
    with fitz.open(output) as document:
        assert document.page_count == 2
        assert "SEARCHABLE OCR TEXT" not in document.load_page(0).get_text()
        assert "SEARCHABLE OCR TEXT" in document.load_page(1).get_text()
        assert document.load_page(0).rect == fitz.Rect(0, 0, 595, 842)


def test_cancel_removes_incomplete_output(tmp_path, monkeypatch) -> None:
    fake_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(ocr_module.PlatformService, "run_cancellable", fake_tesseract)
    source = make_pdf(tmp_path / "cancel.pdf", pages=2)
    output = tmp_path / "cancel_OCR.pdf"
    state = {"cancel": False}

    def progress(current: int, _total: int, _message: str) -> None:
        if current == 1:
            state["cancel"] = True

    with pytest.raises(TaskCancelled):
        run_ocr(
            OCRRequest(
                str(source),
                (0, 1),
                OCRMode.SEARCHABLE_PDF,
                output_path=str(output),
            ),
            progress=progress,
            is_cancelled=lambda: state["cancel"],
        )

    assert not output.exists()
    assert not list(tmp_path.glob(".cancel_OCR-*.pdf"))


def test_missing_bundle_and_output_conflict_are_reported(tmp_path, monkeypatch) -> None:
    source = make_pdf(tmp_path / "input.pdf")
    monkeypatch.setattr(
        ocr_module,
        "bundled_tesseract_runtime",
        lambda: (None, None, "missing chi_tra.traineddata"),
    )
    with pytest.raises(OCRError, match="chi_tra"):
        run_ocr(OCRRequest(str(source), (0,)))

    fake_runtime(tmp_path, monkeypatch)
    output = tmp_path / "exists.txt"
    output.write_text("keep", encoding="utf-8")
    with pytest.raises(OCRError, match="already exists"):
        run_ocr(
            OCRRequest(
                str(source),
                (0,),
                OCRMode.EXTRACT_TEXT,
                output_path=str(output),
            )
        )
    assert output.read_text(encoding="utf-8") == "keep"



@pytest.mark.parametrize("language", ["chi_tra+eng", "eng+chi_tra", "eng", "chi_tra"])
def test_shared_language_contract(tmp_path, monkeypatch, language):
    import core.analysis as analysis
    from core.capabilities import Capability, CapabilityId
    from core.ocr_language import OCR_LANGUAGE, normalize_ocr_language

    canonical = OCR_LANGUAGE if "+" in language else language
    assert normalize_ocr_language(language) == canonical
    fake_runtime(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "language.pdf", 1)
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if command[2] == "stdout":
            return ProcessResult(0, "analysis text", "")
        return fake_tesseract(command, **kwargs)

    monkeypatch.setattr(ocr_module.PlatformService, "run_cancellable", run)
    run_ocr(OCRRequest(str(source), (0,), language=language))
    assert commands[-1][commands[-1].index("-l") + 1] == canonical
    monkeypatch.setattr(analysis, "detect_capabilities", lambda: {
        CapabilityId.OCR: Capability(CapabilityId.OCR, "OCR", True,
                                     path=str(tmp_path / "tesseract.exe"))
    })
    with fitz.open(source) as doc:
        assert analysis._ocr_page_text(doc[0], 150) == "analysis text"
    assert commands[-1][commands[-1].index("-l") + 1] == OCR_LANGUAGE


def test_language_contract_rejects_unknown_language():
    from core.ocr_language import normalize_ocr_language

    with pytest.raises(ValueError, match="Unsupported OCR language"):
        normalize_ocr_language("eng+fra")
