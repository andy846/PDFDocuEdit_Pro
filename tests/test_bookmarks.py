from __future__ import annotations

from pathlib import Path

from core.settings import SettingsManager


def test_bookmarks_round_trip(tmp_path: Path) -> None:
    settings = SettingsManager(tmp_path / "settings.json")
    key = str(tmp_path / "doc.pdf")

    assert settings.get_bookmarks(key) == []

    settings.set_bookmarks(key, [{"page": 0, "title": "Intro"}, {"page": 3, "title": "End"}])
    items = settings.get_bookmarks(key)
    assert items == [{"page": 0, "title": "Intro"}, {"page": 3, "title": "End"}]

    # Removing the list drops the key.
    settings.set_bookmarks(key, [])
    assert settings.get_bookmarks(key) == []


def test_bookmarks_are_keyed_by_resolved_path(tmp_path: Path) -> None:
    settings = SettingsManager(tmp_path / "settings.json")
    key = tmp_path / "doc.pdf"
    settings.set_bookmarks(str(key), [{"page": 1, "title": "A"}])

    assert settings.get_bookmarks(str(key.resolve())) == [{"page": 1, "title": "A"}]
    assert settings.get_bookmarks(str(tmp_path / "other.pdf")) == []


def test_bookmarks_filter_invalid_entries(tmp_path: Path) -> None:
    settings = SettingsManager(tmp_path / "settings.json")
    key = str(tmp_path / "doc.pdf")
    settings.set_bookmarks(
        key,
        [
            {"page": 2, "title": "Valid"},
            {"title": "Missing page"},
            {"page": "not-a-number"},
            "not-a-dict",
        ],
    )
    assert settings.get_bookmarks(key) == [{"page": 2, "title": "Valid"}]


def test_bookmarks_persist_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    first = SettingsManager(path)
    first.set_bookmarks(str(tmp_path / "doc.pdf"), [{"page": 0, "title": "Kept"}])

    second = SettingsManager(path)
    assert second.get_bookmarks(str(tmp_path / "doc.pdf")) == [{"page": 0, "title": "Kept"}]
