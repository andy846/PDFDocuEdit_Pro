from __future__ import annotations

import json
from pathlib import Path

import core.settings as settings_module
from core.settings import SettingsManager


def test_settings_are_atomic_and_persistent(tmp_path: Path) -> None:
    config = tmp_path / "settings.json"
    settings = SettingsManager(config)
    settings.update({"theme": "dark", "window_size": [1440, 900], "animations_enabled": False})

    loaded = SettingsManager(config)
    assert loaded.get_theme() == "dark"
    assert loaded.get_window_size() == (1440, 900)
    assert loaded.get("animations_enabled") is False
    assert not list(tmp_path.glob("*.tmp"))


def test_corrupt_settings_fall_back_to_defaults(tmp_path: Path) -> None:
    config = tmp_path / "settings.json"
    config.write_text("{not json", encoding="utf-8")
    settings = SettingsManager(config)
    assert settings.get_theme() == "system"
    assert settings.get_window_size() == (1280, 820)


def test_recent_files_are_deduplicated_and_missing_files_are_hidden(tmp_path: Path) -> None:
    config = tmp_path / "settings.json"
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    first.write_bytes(b"pdf")
    second.write_bytes(b"pdf")
    settings = SettingsManager(config)
    settings.add_recent_file(first)
    settings.add_recent_file(second)
    settings.add_recent_file(first)
    assert settings.recent_files() == [str(first.resolve()), str(second.resolve())]

    second.unlink()
    assert settings.recent_files() == [str(first.resolve())]
    assert json.loads(config.read_text(encoding="utf-8"))["recent_files"][0] == str(first.resolve())


def test_default_settings_migrate_a_legacy_config_once(tmp_path: Path, monkeypatch) -> None:
    legacy = tmp_path / "portable" / "config.json"
    legacy.parent.mkdir()
    legacy.write_text('{"theme": "dark", "zoom_ratio": 1.5, "unknown": true}', encoding="utf-8")
    destination = tmp_path / "user-config"
    monkeypatch.setattr(settings_module, "config_dir_path", lambda: destination)
    monkeypatch.setattr(settings_module, "legacy_config_paths", lambda: [legacy])

    settings = SettingsManager()
    assert settings.get_theme() == "dark"
    assert settings.get_zoom_ratio() == 1.5
    assert settings.path == destination / "settings.json"
    assert "unknown" not in settings.get_all()


def test_last_save_directory_roundtrip_and_fallback(tmp_path: Path) -> None:
    settings = SettingsManager(tmp_path / "settings.json")
    assert settings.get_last_save_directory() == str(Path.home())

    documents = tmp_path / "documents"
    documents.mkdir()
    assert settings.get_last_save_directory(documents) == str(documents)

    outputs = tmp_path / "outputs"
    outputs.mkdir()
    settings.set_last_save_directory(outputs)
    assert settings.get_last_save_directory() == str(outputs.resolve())
    # A saved folder wins over the fallback.
    assert settings.get_last_save_directory(documents) == str(outputs.resolve())

    reloaded = SettingsManager(tmp_path / "settings.json")
    assert reloaded.get_last_save_directory() == str(outputs.resolve())


def test_print_offsets_roundtrip_and_clamp(tmp_path: Path) -> None:
    settings = SettingsManager(tmp_path / "settings.json")
    assert settings.get_print_offsets() == (0.0, 0.0, 0.0, 0.0)
    settings.set_print_offsets(0.0, 5.0, 0.0, 5.0)
    assert settings.get_print_offsets() == (0.0, 5.0, 0.0, 5.0)

    reloaded = SettingsManager(tmp_path / "settings.json")
    assert reloaded.get_print_offsets() == (0.0, 5.0, 0.0, 5.0)

    settings.set_print_offsets(9999.0, -9999.0, 3.0, 4.0)
    assert settings.get_print_offsets() == (100.0, -100.0, 3.0, 4.0)


def test_print_profile_roundtrip_and_validation(tmp_path: Path) -> None:
    settings = SettingsManager(tmp_path / "settings.json")
    settings.set_print_profile(
        {
            "printer": "Office Printer",
            "copies": 3,
            "collate": False,
            "colour": 1,
            "duplex": 2,
            "dpi": 420,
            "paper": "A4",
            "orientation": 2,
            "scale_mode": 2,
            "scale": 125,
            "center": False,
            "confirm_system_dialog": True,
            "page_mode": "custom",
            "page_range": "2-4",
            "offset_left": 1.0,
            "offset_right": 5.0,
            "offset_top": 2.0,
            "offset_bottom": 6.0,
        }
    )
    reloaded = SettingsManager(tmp_path / "settings.json")
    profile = reloaded.get_print_profile()
    assert profile["printer"] == "Office Printer"
    assert profile["copies"] == 3
    assert profile["duplex"] == 2
    assert profile["dpi"] == 420
    assert profile["paper"] == "A4"
    assert profile["scale"] == 125
    assert profile["page_mode"] == "custom"
    assert profile["page_range"] == "2-4"
    assert reloaded.get_print_offsets() == (1.0, 5.0, 2.0, 6.0)

    reloaded.set(
        "print_profile",
        {
            "copies": 5000,
            "scale": -1,
            "duplex": 99,
            "dpi": 5000,
            "page_mode": "bad",
        },
    )
    safe = reloaded.get_print_profile()
    assert safe["copies"] == 999
    assert safe["scale"] == 10
    assert safe["duplex"] == 3
    assert safe["dpi"] == 600
    assert safe["page_mode"] == "all"


def test_non_object_legacy_config_is_ignored(tmp_path: Path, monkeypatch) -> None:
    legacy = tmp_path / "config.json"
    legacy.write_text('["not", "settings"]', encoding="utf-8")
    destination = tmp_path / "user-config"
    monkeypatch.setattr(settings_module, "config_dir_path", lambda: destination)
    monkeypatch.setattr(settings_module, "legacy_config_paths", lambda: [legacy])

    settings = SettingsManager()
    assert settings.get_theme() == "system"
    assert not settings.path.exists()
