"""Bundled Tesseract OCR service for image-based PDF documents."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import fitz

from .capabilities import bundled_tesseract_runtime
from .pdf_io import set_safe_pdf_metadata, set_safe_pdf_toc, validate_pdf_file
from .platform_service import PlatformService
from .tasks import TaskCancelled

ProgressCallback = Callable[[int, int, str], None]
CancelCallback = Callable[[], bool]


class OCRMode(StrEnum):
    EXTRACT_TEXT = "extract_text"
    SEARCHABLE_PDF = "searchable_pdf"


@dataclass(frozen=True)
class OCRRequest:
    source_path: str
    pages: tuple[int, ...]
    mode: OCRMode = OCRMode.EXTRACT_TEXT
    language: str = "chi_tra+eng"
    dpi: int = 300
    output_path: str | None = None
    password: str | None = None
    overwrite: bool = False


@dataclass(frozen=True)
class OCRResult:
    mode: OCRMode
    pages: tuple[int, ...]
    text: str = ""
    output_path: str | None = None


class OCRError(RuntimeError):
    pass


def run_ocr(
    request: OCRRequest,
    *,
    progress: ProgressCallback | None = None,
    is_cancelled: CancelCallback | None = None,
) -> OCRResult:
    """OCR selected pages using only the bundled Tesseract runtime."""
    executable, tessdata, runtime_error = bundled_tesseract_runtime()
    if executable is None or tessdata is None:
        raise OCRError(runtime_error or "The bundled Tesseract runtime is unavailable.")
    source = Path(request.source_path).expanduser().resolve()
    if not source.is_file():
        raise OCRError(f"Source PDF does not exist: {source}")
    if request.language not in {"eng", "chi_tra", "chi_tra+eng"}:
        raise OCRError(f"Unsupported OCR language: {request.language}")
    if not 72 <= request.dpi <= 600:
        raise OCRError("OCR DPI must be between 72 and 600.")

    with fitz.open(source) as document:
        if document.needs_pass and (
            not request.password or not document.authenticate(request.password)
        ):
            raise OCRError("The PDF password is missing or incorrect.")
        pages = tuple(
            dict.fromkeys(page for page in request.pages if 0 <= page < document.page_count)
        )
        if not pages:
            raise OCRError("Choose at least one valid page for OCR.")

    target = _target_path(request, source)
    if target is not None:
        if target == source:
            raise OCRError("OCR output must not replace the original PDF.")
        if target.exists() and not request.overwrite:
            raise OCRError(f"Output already exists: {target.name}")
        target.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["TESSDATA_PREFIX"] = str(tessdata)
    cancel = is_cancelled or (lambda: False)
    text_pages: list[str] = []
    layer_paths: dict[int, Path] = {}

    with tempfile.TemporaryDirectory(prefix="pdfdocuedit-ocr-") as temp_value:
        temp_dir = Path(temp_value)
        with fitz.open(source) as document:
            if document.needs_pass:
                document.authenticate(request.password or "")
            total = len(pages)
            for position, page_number in enumerate(pages, start=1):
                _check_cancel(cancel)
                if progress:
                    progress(
                        position - 1,
                        total,
                        f"OCR {source.name}: rendering page {page_number + 1}",
                    )
                page = document.load_page(page_number)
                image = temp_dir / f"page-{page_number + 1:06d}.png"
                page.get_pixmap(
                    matrix=fitz.Matrix(request.dpi / 72.0, request.dpi / 72.0),
                    alpha=False,
                ).save(image)
                output_base = temp_dir / f"ocr-{page_number + 1:06d}"
                command = [
                    str(executable),
                    str(image),
                    str(output_base),
                    "-l",
                    request.language,
                    "--dpi",
                    str(request.dpi),
                ]
                if request.mode == OCRMode.SEARCHABLE_PDF:
                    command.extend(["-c", "textonly_pdf=1", "pdf"])
                    expected = output_base.with_suffix(".pdf")
                else:
                    command.append("txt")
                    expected = output_base.with_suffix(".txt")
                result = PlatformService.run_cancellable(
                    command,
                    is_cancelled=cancel,
                    timeout=900,
                    cwd=temp_dir,
                    env=env,
                )
                if result.returncode != 0 or not expected.is_file():
                    detail = (result.stderr or result.stdout).strip()
                    raise OCRError(
                        f"OCR failed for {source.name}, page {page_number + 1}: "
                        f"{detail or 'Tesseract did not create output.'}"
                    )
                if request.mode == OCRMode.EXTRACT_TEXT:
                    text_pages.append(expected.read_text(encoding="utf-8", errors="replace"))
                else:
                    layer_paths[page_number] = expected
                if progress:
                    progress(
                        position,
                        total,
                        f"OCR {source.name}: completed page {page_number + 1}",
                    )

        _check_cancel(cancel)
        if request.mode == OCRMode.EXTRACT_TEXT:
            text = _join_page_text(pages, text_pages)
            if target is not None:
                _atomic_write_text(target, text)
            return OCRResult(request.mode, pages, text=text, output_path=str(target) if target else None)

        if target is None:
            raise OCRError("Choose an output path for the searchable PDF.")
        _create_searchable_pdf(
            source,
            target,
            pages,
            layer_paths,
            request.password,
            cancel,
        )
        return OCRResult(request.mode, pages, output_path=str(target))


def _target_path(request: OCRRequest, source: Path) -> Path | None:
    if not request.output_path:
        return None
    return Path(request.output_path).expanduser().resolve()


def _join_page_text(pages: tuple[int, ...], values: list[str]) -> str:
    sections = [
        f"===== Page {page + 1} =====\n{text.rstrip()}"
        for page, text in zip(pages, values, strict=True)
    ]
    return "\n\n".join(sections).rstrip() + "\n"


def _atomic_write_text(target: Path, text: str) -> None:
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{target.stem}-", suffix=".txt", dir=target.parent
    )
    os.close(handle)
    try:
        Path(temp_name).write_text(text, encoding="utf-8")
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _create_searchable_pdf(
    source: Path,
    target: Path,
    pages: tuple[int, ...],
    layers: dict[int, Path],
    password: str | None,
    is_cancelled: CancelCallback,
) -> None:
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{target.stem}-", suffix=".pdf", dir=target.parent
    )
    os.close(handle)
    expected_page_count = 0
    try:
        with fitz.open(source) as original:
            if original.needs_pass:
                original.authenticate(password or "")
            expected_page_count = original.page_count
            with fitz.open() as output:
                output.insert_pdf(original)
                set_safe_pdf_metadata(output, original.metadata)
                set_safe_pdf_toc(output, original.get_toc())
                for page_number in pages:
                    _check_cancel(is_cancelled)
                    with fitz.open(layers[page_number]) as layer:
                        page = output.load_page(page_number)
                        page.show_pdf_page(page.rect, layer, 0, overlay=True)
                output.save(temp_name, garbage=4, deflate=True)
        _check_cancel(is_cancelled)
        validate_pdf_file(
            temp_name, expected_page_count=expected_page_count
        )
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _check_cancel(is_cancelled: CancelCallback) -> None:
    if is_cancelled():
        raise TaskCancelled

