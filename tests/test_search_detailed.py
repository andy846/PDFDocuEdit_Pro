from __future__ import annotations

from pathlib import Path

import fitz

from core.pdf_engine import PdfEngine, search_pdf_file


def make_searchable_pdf(path: Path) -> Path:
    with fitz.open() as document:
        page = document.new_page(width=595, height=842)
        page.insert_text((72, 96), "The Quick Brown fox. quick quick quickness.")
        page.insert_text((72, 160), "Another line with Quick and quick.")
        document.save(path)
    return path


def test_detailed_search_is_case_insensitive_by_default(tmp_path: Path) -> None:
    source = make_searchable_pdf(tmp_path / "search.pdf")
    engine = PdfEngine()
    engine.open(source)
    hits = engine.search_text_detailed("quick")
    # Matches: Quick, quick, quick, quickness (substring), Quick, quick = 6
    assert len(hits) == 1
    assert hits[0].page == 0
    assert len(hits[0].rects) == 6
    assert "Quick" in hits[0].context
    engine.close()


def test_detailed_search_case_sensitive(tmp_path: Path) -> None:
    source = make_searchable_pdf(tmp_path / "case.pdf")
    engine = PdfEngine()
    engine.open(source)
    hits = engine.search_text_detailed("Quick", case_sensitive=True)
    assert len(hits) == 1
    assert len(hits[0].rects) == 2
    engine.close()


def test_detailed_search_whole_word(tmp_path: Path) -> None:
    source = make_searchable_pdf(tmp_path / "word.pdf")
    engine = PdfEngine()
    engine.open(source)
    hits = engine.search_text_detailed("quick", whole_word=True)
    # Whole words only: "quickness" and "quickness." excluded, punctuation
    # attached to a word is ignored.
    assert len(hits[0].rects) == 5
    engine.close()


def test_detailed_search_limited_pages_and_empty(tmp_path: Path) -> None:
    source = make_searchable_pdf(tmp_path / "pages.pdf")
    engine = PdfEngine()
    engine.open(source)
    assert engine.search_text_detailed("") == []
    assert engine.search_text_detailed("missing") == []
    assert engine.search_text_detailed("quick", pages=[99]) == []
    engine.close()


def test_search_pdf_file_works_without_opening_engine(tmp_path: Path) -> None:
    source = make_searchable_pdf(tmp_path / "file.pdf")
    hits = search_pdf_file(str(source), "quick", case_sensitive=True)
    assert len(hits) == 1
    assert len(hits[0].rects) == 4
    assert all(isinstance(rect, fitz.Rect) for rect in hits[0].rects)
