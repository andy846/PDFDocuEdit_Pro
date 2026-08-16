from __future__ import annotations

from core.commands import Command, filter_commands


def make_commands() -> list[Command]:
    return [
        Command("merge", "Merge PDFs…", "Ctrl+M", "Tools", lambda: None),
        Command("compress", "Compress PDF…", "", "Tools", lambda: None),
        Command("save", "Save", "Ctrl+S", "File", lambda: None),
        Command("nav_outline", "Show Outline Panel", "", "View", lambda: None),
    ]


def test_empty_query_returns_everything() -> None:
    commands = make_commands()
    assert filter_commands(commands, "") == commands
    assert filter_commands(commands, "   ") == commands


def test_subsequence_matching_is_case_insensitive() -> None:
    commands = make_commands()
    result = filter_commands(commands, "MgP")
    assert [c.id for c in result] == ["merge"]


def test_matching_against_shortcut() -> None:
    commands = make_commands()
    result = filter_commands(commands, "ctrl+s")
    assert [c.id for c in result] == ["save"]


def test_no_match_returns_empty() -> None:
    assert filter_commands(make_commands(), "zzz") == []


def test_subsequence_must_preserve_order() -> None:
    commands = [
        Command("alpha", "alpha", "", "T", lambda: None),
        Command("beta", "beta", "", "T", lambda: None),
    ]
    assert [c.id for c in filter_commands(commands, "ph")] == ["alpha"]
    assert [c.id for c in filter_commands(commands, "hp")] == []
