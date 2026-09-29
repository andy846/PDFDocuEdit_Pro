"""Detailed, streaming PDF folder search and report data.

The older ``core.tools.deep_search`` interface remains available to callers that
expect one snippet per matching page.  This module provides occurrence-level
results for the Deep Search window and its exports.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import fitz

from core.tools import ToolError, _pdf_files


@dataclass(frozen=True, slots=True)
class SearchHit:
    path: str
    filename: str
    page: int  # one-based for display and export
    keyword: str
    source: str  # "text" or "barcode"
    context: str
    position: int


@dataclass(frozen=True, slots=True)
class SearchFile:
    path: str
    filename: str
    pages: int
    matching_pages: int
    matches: int
    no_text: bool


@dataclass(frozen=True, slots=True)
class SearchIssue:
    path: str
    filename: str
    message: str


@dataclass(frozen=True, slots=True)
class SearchBatch:
    hits: tuple[SearchHit, ...] = ()
    file: SearchFile | None = None
    issue: SearchIssue | None = None


@dataclass(frozen=True, slots=True)
class SearchRun:
    folder: str
    keywords: tuple[str, ...]
    files_found: int
    files_processed: int
    matching_files: int
    matches: int
    errors: int
    no_text_files: int


def parse_keywords(query: str) -> tuple[str, ...]:
    """Parse comma-separated literal terms, removing case-insensitive duplicates."""
    result: list[str] = []
    seen: set[str] = set()
    for part in query.split(","):
        keyword = part.strip()
        folded = keyword.casefold()
        if keyword and folded not in seen:
            result.append(keyword)
            seen.add(folded)
    if not result:
        raise ToolError("Enter text to search for.")
    return tuple(result)


def _context(value: str, start: int, end: int) -> str:
    return " ".join(value[max(0, start - 60):min(len(value), end + 90)].split())


def _matches(
    value: str,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
    path: str,
    filename: str,
    page: int,
    source: str,
) -> list[SearchHit]:
    found: list[SearchHit] = []
    for keyword, pattern in patterns:
        for match in pattern.finditer(value):
            found.append(SearchHit(
                path, filename, page, keyword, source,
                _context(value, match.start(), match.end()), match.start(),
            ))
    found.sort(key=lambda hit: (hit.position, hit.keyword.casefold()))
    return found


def _barcode_values(page: fitz.Page) -> Iterable[str]:
    """Decode each barcode independently so occurrence counts remain accurate."""
    try:
        from PIL import Image
        from pyzbar.pyzbar import decode
    except ImportError:
        return ()
    pixmap = page.get_pixmap(dpi=150, alpha=False)
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    return tuple(item.data.decode("utf-8", errors="replace") for item in decode(image))


def search_folder_detailed(
    folder_path: str | Path,
    query: str,
    include_subfolders: bool = True,
    search_barcodes: bool = False,
    *,
    on_batch: Callable[[SearchBatch], None],
    progress: Callable[[int, int, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    batch_size: int = 200,
) -> SearchRun:
    """Stream occurrence-level results without retaining them all in RAM."""
    folder = Path(folder_path).expanduser().resolve()
    if not folder.is_dir():
        raise ToolError("Choose a valid folder to search.")
    keywords = parse_keywords(query)
    patterns = tuple((term, re.compile(re.escape(term), re.IGNORECASE)) for term in keywords)
    files = _pdf_files(folder, include_subfolders)
    pending: list[SearchHit] = []
    processed = matched_files = matches = errors = no_text_files = 0

    def flush() -> None:
        if pending:
            on_batch(SearchBatch(hits=tuple(pending)))
            pending.clear()

    for path in files:
        if is_cancelled and is_cancelled():
            break
        path_text = str(path)
        page_matches: set[int] = set()
        file_matches = page_count = searchable_pages = 0
        try:
            with fitz.open(path) as document:
                page_count = len(document)
                for page_index, page in enumerate(document):
                    if is_cancelled and is_cancelled():
                        break
                    if progress:
                        progress(processed, len(files), f"{path.name} · page {page_index + 1}/{page_count}")
                    content = page.get_text()
                    if content.strip():
                        searchable_pages += 1
                    page_number = page_index + 1
                    hits = _matches(content, patterns, path_text, path.name, page_number, "text")
                    if search_barcodes:
                        for value in _barcode_values(page):
                            hits.extend(_matches(
                                value, patterns, path_text, path.name, page_number, "barcode"
                            ))
                    if hits:
                        page_matches.add(page_number)
                        file_matches += len(hits)
                        matches += len(hits)
                        pending.extend(hits)
                        if len(pending) >= batch_size:
                            flush()
                if is_cancelled and is_cancelled():
                    break
            flush()
            no_text = page_count > 0 and searchable_pages == 0
            no_text_files += int(no_text)
            matched_files += int(file_matches > 0)
            on_batch(SearchBatch(file=SearchFile(
                path_text, path.name, page_count, len(page_matches), file_matches, no_text
            )))
        except Exception as exc:
            flush()
            errors += 1
            on_batch(SearchBatch(issue=SearchIssue(
                path_text, path.name, str(exc) or exc.__class__.__name__
            )))
        processed += 1
        if progress:
            progress(processed, len(files), path.name)
    flush()
    return SearchRun(
        str(folder), keywords, len(files), processed, matched_files,
        matches, errors, no_text_files,
    )
