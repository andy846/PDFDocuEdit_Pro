from __future__ import annotations

import fitz
from PyQt6.QtCore import QPointF, QRectF

from ui.page_overlay import (
    extract_words_in_rect,
    pdf_rect_to_widget,
    scale_for_pixmap,
    widget_point_to_pdf,
    words_intersecting,
)


def make_page() -> fitz.Page:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 96), "First line of text")
    page.insert_text((72, 120), "Second line here")
    return page


def test_scale_for_pixmap() -> None:
    page_rect = fitz.Rect(0, 0, 595, 842)
    assert scale_for_pixmap(page_rect, zoom=2.0) == 0.5
    assert scale_for_pixmap(page_rect, zoom=1.0) == 1.0
    assert scale_for_pixmap(page_rect, zoom=0.5) == 2.0


def test_coordinate_round_trip() -> None:
    page_rect = fitz.Rect(0, 0, 595, 842)
    scale = 0.5  # rendered at zoom 2
    pdf = widget_point_to_pdf(QPointF(100, 200), page_rect, scale)
    assert abs(pdf.x - 50) < 1e-6
    assert abs(pdf.y - 100) < 1e-6

    rect = pdf_rect_to_widget(fitz.Rect(50, 100, 150, 200), page_rect, scale)
    assert rect == QRectF(100, 200, 200, 200)


def test_words_intersecting_and_extraction() -> None:
    page = make_page()
    rect = fitz.Rect(60, 85, 250, 105)  # first line only
    kept = words_intersecting(page, rect)
    assert kept, "no words found"
    text = " ".join(word for _rect, word in kept)
    assert "First" in text
    assert "Second" not in text

    extracted = extract_words_in_rect(page, rect)
    assert "First" in extracted
    assert "line" in extracted

    empty = extract_words_in_rect(page, fitz.Rect(400, 400, 500, 500))
    assert empty == ""
