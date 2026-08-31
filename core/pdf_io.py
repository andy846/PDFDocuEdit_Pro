"""Shared safety helpers for PDF metadata and completed output files."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import fitz

PDF_METADATA_KEYS = frozenset(
    {
        "title",
        "author",
        "subject",
        "keywords",
        "creator",
        "producer",
        "creationDate",
        "modDate",
        "trapped",
    }
)


class PdfValidationError(RuntimeError):
    """Raised when a newly written PDF cannot be safely reopened."""


def sanitize_pdf_text(value: object) -> str:
    """Return text that PyMuPDF can safely encode as a PDF string.

    Some scanner-generated PDFs contain invalid UTF-8 bytes in their Info
    dictionary. PyMuPDF exposes those bytes as ``surrogateescape`` code points
    (for example ``\udcc0``), which then fail when passed back to
    ``set_metadata`` or ``set_toc``. Drop byte-surrogate escapes, replace any
    other unpaired surrogate, and discard NUL characters.
    """

    text = "" if value is None else str(value)
    cleaned: list[str] = []
    for character in text:
        codepoint = ord(character)
        if character == "\x00" or 0xDC80 <= codepoint <= 0xDCFF:
            continue
        if 0xD800 <= codepoint <= 0xDFFF:
            cleaned.append("\ufffd")
        else:
            cleaned.append(character)
    return "".join(cleaned)


def sanitize_pdf_metadata(metadata: Mapping[str, object] | None) -> dict[str, str]:
    """Keep supported Info keys and make all values safe PDF strings."""

    if not metadata:
        return {}
    return {
        key: sanitize_pdf_text(value)
        for key, value in metadata.items()
        if key in PDF_METADATA_KEYS
    }


def set_safe_pdf_metadata(
    document: fitz.Document, metadata: Mapping[str, object] | None
) -> None:
    """Set a sanitized PDF Info dictionary on *document*."""

    document.set_metadata(sanitize_pdf_metadata(metadata))


def _sanitize_pdf_value(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_pdf_text(value)
    if isinstance(value, dict):
        return {key: _sanitize_pdf_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_pdf_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_pdf_value(item) for item in value)
    return value


def sanitize_pdf_toc(toc: Iterable[list[Any]] | None) -> list[list[Any]]:
    """Sanitize outline titles and string destinations recursively."""

    if not toc:
        return []
    return [list(_sanitize_pdf_value(entry)) for entry in toc]


def set_safe_pdf_toc(document: fitz.Document, toc: Iterable[list[Any]] | None) -> None:
    """Set a sanitized outline on *document*."""

    document.set_toc(sanitize_pdf_toc(toc))


def validate_pdf_file(
    path: str | os.PathLike[str],
    *,
    password: str | None = None,
    expected_page_count: int | None = None,
) -> None:
    """Reopen a completed PDF and verify its page tree before publication."""

    source = Path(path)
    try:
        if not source.is_file() or source.stat().st_size == 0:
            raise PdfValidationError("The generated PDF is empty or missing.")
        with fitz.open(source) as document:
            if document.needs_pass and (
                not password or not document.authenticate(password)
            ):
                raise PdfValidationError(
                    "The generated PDF could not be reopened with its password."
                )
            if expected_page_count is not None and document.page_count != int(
                expected_page_count
            ):
                raise PdfValidationError(
                    "The generated PDF has an unexpected page count "
                    f"({document.page_count} instead of {expected_page_count})."
                )
            if document.page_count < 1:
                raise PdfValidationError("The generated PDF has no pages.")
            for page_number in range(document.page_count):
                page = document.load_page(page_number)
                _ = page.rect
                page.get_contents()
    except PdfValidationError:
        raise
    except Exception as exc:
        raise PdfValidationError(
            f"The generated PDF could not be reopened: {exc}"
        ) from exc
