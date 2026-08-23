"""Shared command registry for the command palette and shortcut reference."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Command:
    """One executable application command with metadata for discovery UIs."""

    id: str
    label: str
    shortcut: str
    section: str
    handler: Callable[[], None]
    enabled: Callable[[], bool] | None = field(default=None, compare=False)
    default_shortcut: str = ""

    def is_enabled(self) -> bool:
        return self.enabled is None or self.enabled()


def _is_subsequence(needle: str, haystack: str) -> bool:
    position = 0
    for character in needle:
        position = haystack.find(character, position)
        if position < 0:
            return False
        position += 1
    return True


def filter_commands(commands: list[Command], query: str) -> list[Command]:
    """Return commands whose label or shortcut contains the query as a
    case-insensitive subsequence. An empty query returns every command."""
    needle = query.strip().casefold()
    if not needle:
        return list(commands)

    def matches(value: str) -> bool:
        return _is_subsequence(needle, value.casefold())

    return [
        command
        for command in commands
        if matches(command.label) or matches(command.shortcut)
    ]
