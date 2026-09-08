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


def test_default_lookup_reaches_machine_classes(monkeypatch):
    import winreg

    monkeypatch.setattr(module, "_user_choice_prog_id", lambda _: None)
    calls = []
    def read(root, path):
        calls.append((root, path))
        return "Machine.PDF" if root == winreg.HKEY_LOCAL_MACHINE else None
    monkeypatch.setattr(module, "_read_default", read)
    assert module.default_app_extension(".pdf") == "Machine.PDF"
    assert [root for root, _ in calls] == [
        winreg.HKEY_CURRENT_USER, winreg.HKEY_CLASSES_ROOT, winreg.HKEY_LOCAL_MACHINE
    ]


def test_unregister_preserves_other_registrations(monkeypatch):
    import sys
    from types import SimpleNamespace

    class Key(str):
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass

    keys = {}
    def create(_root, path):
        parts = path.split("\\")
        for index in range(1, len(parts) + 1):
            keys.setdefault("\\".join(parts[:index]), {})
        return Key(path)
    def open_key(_root, path, *_):
        if path not in keys:
            raise FileNotFoundError(path)
        return Key(path)
    def query(key, name):
        if name not in keys[key]:
            raise FileNotFoundError(name)
        return keys[key][name], 1
    def info(key):
        children = {path[len(key)+1:].split("\\")[0] for path in keys
                    if path.startswith(key + "\\")}
        return len(children), len(keys[key]), 0
    def delete_key(_root, path):
        assert info(path)[:2] == (0, 0)
        del keys[path]
    fake = SimpleNamespace(
        HKEY_CURRENT_USER=1, HKEY_CLASSES_ROOT=2, HKEY_LOCAL_MACHINE=3,
        KEY_READ=1, KEY_WRITE=2, REG_SZ=1,
        CreateKey=create, OpenKey=open_key, CloseKey=lambda _: None,
        QueryValueEx=query, QueryInfoKey=info, DeleteKey=delete_key,
        SetValueEx=lambda key, name, _zero, _kind, value: keys[key].__setitem__(name, value),
        DeleteValue=lambda key, name: keys[key].__delitem__(name),
    )
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module, "_executable", lambda: "editor.exe")
    monkeypatch.setattr(module, "is_default_app", lambda _: True)
    assert module.register_default_app()
    pdf = r"Software\Classes\.pdf"
    keys[pdf]["OtherValue"] = "keep"
    open_with = pdf + r"\OpenWithProgids"
    create(1, open_with)
    keys[open_with].update({module.PROG_ID: "", "Other.PDF": ""})
    keys[r"Software\Classes\.ps"][""] = "Other.PS"
    choice = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.pdf\UserChoice"
    create(1, choice)
    keys[choice]["ProgId"] = "Other.PDF"
    assert module.unregister_default_app()
    assert keys[pdf] == {"OtherValue": "keep"}
    assert keys[open_with] == {"Other.PDF": ""}
    assert keys[r"Software\Classes\.ps"][""] == "Other.PS"
    assert keys[choice]["ProgId"] == "Other.PDF"
    assert r"Software\Classes\.eps" not in keys
    assert not any(module.PROG_ID in path for path in keys)
    assert module.unregister_default_app()  # idempotent
