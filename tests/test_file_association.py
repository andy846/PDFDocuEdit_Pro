"""Default-app detection logic (registry reads are mocked, never written)."""

from __future__ import annotations

import core.file_association as module


def test_is_default_app_requires_all_extensions(monkeypatch) -> None:
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        module,
        "default_app_extension",
        lambda ext: module.PROG_ID if ext == ".pdf" else "Acrobat.Document",
    )
    assert not module.is_default_app()

    monkeypatch.setattr(
        module, "default_app_extension", lambda ext: module.PROG_ID
    )
    assert module.is_default_app()


def test_is_default_app_false_when_not_frozen(monkeypatch) -> None:
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.sys, "frozen", False, raising=False)
    monkeypatch.setattr(
        module, "default_app_extension", lambda ext: module.PROG_ID
    )
    assert not module.is_default_app()


def test_default_app_extension_prefers_user_choice(monkeypatch) -> None:
    monkeypatch.setattr(
        module, "_user_choice_prog_id", lambda ext: "Some.Other.ProgId"
    )
    monkeypatch.setattr(module, "_read_default", lambda root, path: module.PROG_ID)
    assert module.default_app_extension(".pdf") == "Some.Other.ProgId"

    monkeypatch.setattr(module, "_user_choice_prog_id", lambda ext: None)
    assert module.default_app_extension(".pdf") == module.PROG_ID
