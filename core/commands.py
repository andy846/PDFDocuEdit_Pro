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
    scope: str = "window"
    alternate_shortcuts: tuple[str, ...] = ()

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
        if matches(command.label) or matches(command.shortcut) or matches(command.section)
        or any(matches(value) for value in command.alternate_shortcuts)
    ]


def scopes_overlap(left: str, right: str) -> bool:
    return left == right or {left, right} <= {"window", "canvas"}


def shortcut_conflict(left: str, right: str) -> bool:
    """Equal or prefix sequences are ambiguous in an overlapping scope."""
    from PyQt6.QtGui import QKeySequence
    a, b = QKeySequence(left), QKeySequence(right)
    if a.isEmpty() or b.isEmpty():
        return False
    return a.matches(b) != QKeySequence.SequenceMatch.NoMatch or b.matches(a) != QKeySequence.SequenceMatch.NoMatch


def command_shortcuts(command, values=None):
    primary = (values or {}).get(command.id, command.shortcut)
    if not primary:
        return ()
    alternatives = command.alternate_shortcuts if primary == command.shortcut else ()
    return (primary, *alternatives)


def find_shortcut_conflict(commands, values):
    for index, command in enumerate(commands):
        for other in commands[index + 1:]:
            if scopes_overlap(command.scope, other.scope) and any(
                    shortcut_conflict(left, right)
                    for left in command_shortcuts(command, values)
                    for right in command_shortcuts(other, values)):
                return command, other
    return None
