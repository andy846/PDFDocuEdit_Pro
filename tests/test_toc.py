from __future__ import annotations

from ui.outline_panel import toc_to_zero_based


def test_toc_pages_converted_to_zero_based() -> None:
    toc = [[1, "Chapter 1", 1], [2, "Section", 1], [1, "Chapter 2", 3]]
    assert toc_to_zero_based(toc) == [
        (1, "Chapter 1", 0),
        (2, "Section", 0),
        (1, "Chapter 2", 2),
    ]


def test_toc_levels_clamped_and_titles_preserved() -> None:
    toc = [[0, "Root", 2], [7, "Deep", 4]]
    converted = toc_to_zero_based(toc)
    assert converted[0] == (1, "Root", 1)
    assert converted[1] == (7, "Deep", 3)


def test_empty_toc() -> None:
    assert toc_to_zero_based([]) == []
