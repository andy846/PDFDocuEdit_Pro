from __future__ import annotations

import fitz
import pytest

from core.font_inspector import (
    inspect_font_at,
    remove_subset_prefix,
    suggested_annotation_font,
)


def test_inspect_font_at_returns_span_resource_and_style() -> None:
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text(
            (72, 96),
            "Inspector sample",
            fontname="helv",
            fontsize=14,
            color=(1, 0, 0),
        )

        result = inspect_font_at(page, fitz.Point(80, 90))

        assert result is not None
        assert result["text"] == "Inspector sample"
        assert result["raw_font"] == "Helvetica"
        assert result["display_font"] == "Helvetica"
        assert result["suggested_font"] == "Helv"
        assert result["usable_for_annotations"] is True
        assert result["size"] == pytest.approx(14.0)
        assert result["color"] == "#ff0000"
        assert result["font_type"] == "Type1"
        assert result["encoding"] == "WinAnsiEncoding"
        assert result["embedded"] is False
        assert fitz.Rect(result["bbox"]).contains(fitz.Point(80, 90))


def test_inspect_font_at_returns_none_for_whitespace() -> None:
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 96), "Text")

        assert inspect_font_at(page, fitz.Point(400, 400)) is None


def test_pdf_font_names_are_made_reusable() -> None:
    assert remove_subset_prefix("ABCDEF+Arial-BoldMT") == (
        "Arial-BoldMT",
        True,
    )
    assert suggested_annotation_font("ABCDEF+Arial-BoldMT") == "Arial"
    assert suggested_annotation_font("Helvetica-Bold") == "Helv"
    assert suggested_annotation_font("Times-Roman") == "Times-Roman"
