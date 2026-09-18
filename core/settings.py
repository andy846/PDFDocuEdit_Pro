"""Persistent application settings stored in the per-user config directory."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from core.diagnostics import log_failure

from .resources import config_dir_path, legacy_config_paths


class SettingsManager:
    DEFAULT_SETTINGS: dict[str, Any] = {
        "window_size": [1280, 820],
        "window_position": None,
        "window_maximized": False,
        "zoom_ratio": 1.0,
        "last_directory": None,
        "last_save_directory": None,
        "theme": "system",
        "left_panel_collapsed": False,
        "right_panel_visible": False,
        "animations_enabled": True,
        "recent_files": [],
        "bookmarks": {},
        "ghostscript_path": None,
        "libreoffice_path": None,
        "print_offset_left_mm": 0.0,
        "print_offset_right_mm": 0.0,
        "print_offset_top_mm": 0.0,
        "print_offset_bottom_mm": 0.0,
        "print_profile": {},
        "split_orientation": "horizontal",
        "annotation_defaults": {},
        "annotation_recent_colors": [],
        "custom_stamps": {},
        "verapdf_path": None,
        "split_sync_page": False,
        "split_sync_zoom": False,
        "default_app_prompt_shown": False,
        "shortcut_overrides": {},
    }

    def __init__(self, config_file: str | os.PathLike[str] | None = None):
        self._uses_default_path = config_file is None
        self._config_file = Path(config_file) if config_file else None
        self._save_failed_warned = False
        self._settings = self.DEFAULT_SETTINGS.copy()
        self._migrate_legacy_config()
        self._load()

    @property
    def path(self) -> Path:
        """The settings file path, resolved lazily so reads create nothing."""
        return self._config_file or (config_dir_path() / "settings.json")

    def _migrate_legacy_config(self) -> None:
        if self.path.exists() or not self._uses_default_path:
            return
        for legacy in legacy_config_paths():
            if not legacy.exists() or legacy.resolve() == self.path.resolve():
                continue
            try:
                data = json.loads(legacy.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    continue
                allowed = {
                    key: value
                    for key, value in data.items()
                    if key in self.DEFAULT_SETTINGS
                }
                self._settings.update(allowed)
                self._save()
                return
            except (OSError, json.JSONDecodeError, TypeError):
                continue

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self._settings = {**self.DEFAULT_SETTINGS, **loaded}
        except (OSError, json.JSONDecodeError, TypeError):
            self._settings = self.DEFAULT_SETTINGS.copy()

    def _save(self) -> None:
        """Persist settings atomically; degrade to in-memory mode on failure.

        A read-only preferences directory (permissions, sandbox) must never
        crash the application: settings simply stay in memory for the session.
        """
        config_file = self.path
        temp_name = ""
        try:
            config_file.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(self._settings, indent=2, ensure_ascii=False)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=config_file.parent,
                prefix="settings-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
                temp_name = handle.name
            os.replace(temp_name, config_file)
        except OSError as exc:
            if not self._save_failed_warned:
                self._save_failed_warned = True
                print(
                    "PDFDocuEdit Pro: could not save settings "
                    f"({exc}); preferences are kept in memory only.",
                    file=sys.stderr,
                )
        finally:
            if temp_name and os.path.exists(temp_name):
                try:
                    os.unlink(temp_name)
                except OSError:
                    log_failure('settings._save: fallback after failure', 10)
                    pass

    def get(self, key: str, default: Any = None) -> Any:
        """Return the fallback for missing/null values; preserve false, zero and empty values."""
        if key in self._settings and self._settings[key] is not None:
            return self._settings[key]
        if default is not None:
            return default
        return self.DEFAULT_SETTINGS.get(key)

    def set(self, key: str, value: Any) -> None:
        self._settings[key] = value
        self._save()

    def update(self, values: dict[str, Any]) -> None:
        self._settings.update(values)
        self._save()

    def get_all(self) -> dict[str, Any]:
        return self._settings.copy()

    def get_shortcut_overrides(self) -> dict[str, str]:
        value = self.get("shortcut_overrides", {})
        if not isinstance(value, dict):
            return {}
        return {
            str(command_id): str(sequence)
            for command_id, sequence in value.items()
            if isinstance(command_id, str) and isinstance(sequence, str)
        }

    def set_shortcut_overrides(self, overrides: dict[str, str]) -> None:
        cleaned = {
            str(command_id): str(sequence)
            for command_id, sequence in overrides.items()
            if isinstance(command_id, str) and isinstance(sequence, str)
        }
        self.set("shortcut_overrides", cleaned)

    def get_custom_stamps(self) -> dict[str, str]:
        """Return cached stamp choices; validate files only when used."""
        value = self.get("custom_stamps", {})
        if not isinstance(value, dict):
            return {}
        stamps: dict[str, str] = {}
        for raw_name, raw_path in value.items():
            name = str(raw_name).strip()
            path = Path(str(raw_path)).expanduser()
            if name and path.suffix.casefold() in {
                ".png",
                ".jpg",
                ".jpeg",
            }:
                stamps[name] = os.path.abspath(path)
        return stamps

    def set_custom_stamps(self, stamps: dict[str, str]) -> None:
        """Persist a normalized name-to-image mapping for custom stamps."""
        cleaned = {
            str(name).strip(): str(Path(path).expanduser().resolve())
            for name, path in stamps.items()
            if str(name).strip()
            and Path(path).expanduser().is_file()
            and Path(path).suffix.casefold() in {".png", ".jpg", ".jpeg"}
        }
        self.set("custom_stamps", cleaned)

    def reset(self) -> None:
        self._settings = self.DEFAULT_SETTINGS.copy()
        self._save()

    def get_window_size(self) -> tuple[int, int]:
        value = self.get("window_size", [1280, 820])
        try:
            return max(960, int(value[0])), max(640, int(value[1]))
        except (TypeError, ValueError, IndexError):
            return 1280, 820

    def set_window_size(self, width: int, height: int) -> None:
        self.set("window_size", [width, height])

    def get_window_position(self) -> tuple[int, int] | None:
        value = self.get("window_position")
        try:
            return (int(value[0]), int(value[1])) if value else None
        except (TypeError, ValueError, IndexError):
            return None

    def set_window_position(self, x: int, y: int) -> None:
        self.set("window_position", [x, y])

    def get_zoom_ratio(self) -> float:
        try:
            return min(4.0, max(0.25, float(self.get("zoom_ratio", 1.0))))
        except (TypeError, ValueError):
            return 1.0

    def set_zoom_ratio(self, ratio: float) -> None:
        self.set("zoom_ratio", min(4.0, max(0.25, float(ratio))))

    def get_last_directory(self) -> str:
        value = self.get("last_directory")
        if value and Path(value).expanduser().is_dir():
            return str(Path(value).expanduser())
        return str(Path.home())

    def set_last_directory(self, directory: str | os.PathLike[str]) -> None:
        path = Path(directory).expanduser()
        if path.is_dir():
            self.set("last_directory", str(path.resolve()))

    def get_last_save_directory(
        self, fallback: str | os.PathLike[str] | None = None
    ) -> str:
        """The remembered Save-As folder, or a fallback folder (typically the
        open document's), or the home directory.

        Keep it separate from the open dialog's last directory: users often
        open from one folder and save into another.
        """
        value = self.get("last_save_directory")
        if value and Path(value).expanduser().is_dir():
            return str(Path(value).expanduser())
        if fallback:
            candidate = Path(fallback).expanduser()
            if candidate.is_dir():
                return str(candidate)
        return str(Path.home())

    def set_last_save_directory(self, directory: str | os.PathLike[str]) -> None:
        path = Path(directory).expanduser()
        if path.is_dir():
            self.set("last_save_directory", str(path.resolve()))

    def get_theme(self) -> str:
        value = str(self.get("theme", "system")).lower()
        return value if value in {"system", "light", "dark"} else "system"

    def set_theme(self, theme: str) -> None:
        self.set("theme", theme if theme in {"system", "light", "dark"} else "system")

    def recent_files(self) -> list[str]:
        values = self.get("recent_files", [])
        # Cached UI data: never probe recent paths here (they may be network paths).
        return [str(Path(value)) for value in values if isinstance(value, str) and value][:10]

    def add_recent_file(self, path: str | os.PathLike[str]) -> None:
        value = os.path.abspath(os.path.expanduser(os.fspath(path)))
        recent = [item for item in self.recent_files() if item != value]
        recent.insert(0, value)
        recent = recent[:10]
        details = dict(self.get("recent_file_info", {}) or {})
        details[value] = dict(details.get(value, {}), last_opened=datetime.now().isoformat(timespec="minutes"))
        self.update({"recent_files": recent, "recent_file_info": {key: details[key] for key in recent if key in details}})

    def get_print_offsets(self) -> tuple[float, float, float, float]:
        """Default print shifts in mm: (left, right, top, bottom).

        Positive right/bottom values shift the printed content left/up,
        which centres output on printers with asymmetric printable areas.
        """
        values: list[float] = []
        for key in (
            "print_offset_left_mm",
            "print_offset_right_mm",
            "print_offset_top_mm",
            "print_offset_bottom_mm",
        ):
            try:
                values.append(min(100.0, max(-100.0, float(self.get(key, 0.0)))))
            except (TypeError, ValueError):
                values.append(0.0)
        return (values[0], values[1], values[2], values[3])

    def set_print_offsets(
        self, left: float, right: float, top: float, bottom: float
    ) -> None:
        def clamp(value: float) -> float:
            return min(100.0, max(-100.0, float(value)))

        self.update(
            {
                "print_offset_left_mm": clamp(left),
                "print_offset_right_mm": clamp(right),
                "print_offset_top_mm": clamp(top),
                "print_offset_bottom_mm": clamp(bottom),
            }
        )

    @staticmethod
    def _normalise_print_profile(value: Any) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "printer": "",
            "copies": 1,
            "collate": True,
            "colour": 0,
            "duplex": 0,
            "dpi": 300,
            "paper": "PDF page size",
            "orientation": 0,
            "scale_mode": 0,
            "scale": 100,
            "center": True,
            "confirm_system_dialog": False,
            "page_mode": "all",
            "page_range": "",
        }
        raw = value if isinstance(value, dict) else {}

        def integer(key: str, minimum: int, maximum: int) -> int:
            try:
                return min(maximum, max(minimum, int(raw.get(key, defaults[key]))))
            except (TypeError, ValueError):
                return int(defaults[key])

        paper = str(raw.get("paper", defaults["paper"]))
        if paper not in {"PDF page size", "A4", "A3", "A5", "Letter"}:
            paper = str(defaults["paper"])
        page_mode = str(raw.get("page_mode", defaults["page_mode"]))
        if page_mode not in {"all", "current", "custom"}:
            page_mode = str(defaults["page_mode"])
        return {
            "printer": str(raw.get("printer", ""))[:500],
            "copies": integer("copies", 1, 999),
            "collate": bool(raw.get("collate", defaults["collate"])),
            "colour": integer("colour", 0, 1),
            "duplex": integer("duplex", 0, 3),
            "dpi": integer("dpi", 72, 600),
            "paper": paper,
            "orientation": integer("orientation", 0, 2),
            "scale_mode": integer("scale_mode", 0, 2),
            "scale": integer("scale", 10, 400),
            "center": bool(raw.get("center", defaults["center"])),
            "confirm_system_dialog": bool(
                raw.get(
                    "confirm_system_dialog",
                    defaults["confirm_system_dialog"],
                )
            ),
            "page_mode": page_mode,
            "page_range": str(raw.get("page_range", ""))[:1000],
        }

    def get_print_profile(self) -> dict[str, Any]:
        """Return the last accepted single-document print choices."""
        return self._normalise_print_profile(self.get("print_profile", {}))

    def set_print_profile(self, details: dict[str, Any]) -> None:
        profile = self._normalise_print_profile(details)

        def offset(key: str) -> float:
            try:
                return min(100.0, max(-100.0, float(details.get(key, 0.0))))
            except (TypeError, ValueError):
                return 0.0

        self.update(
            {
                "print_profile": profile,
                "print_offset_left_mm": offset("offset_left"),
                "print_offset_right_mm": offset("offset_right"),
                "print_offset_top_mm": offset("offset_top"),
                "print_offset_bottom_mm": offset("offset_bottom"),
            }
        )

    def get_bookmarks(self, path: str) -> list[dict]:
        """Return the bookmark list for a document as [{"page": int, "title": str}]."""
        value = self.get("bookmarks", {})
        if not isinstance(value, dict):
            return []
        key = str(Path(path).expanduser().resolve())
        items = value.get(key, [])
        if not isinstance(items, list):
            return []
        bookmarks: list[dict] = []
        for item in items:
            if not isinstance(item, dict) or "page" not in item:
                continue
            try:
                page = int(item["page"])
            except (TypeError, ValueError):
                continue
            bookmarks.append({"page": page, "title": str(item.get("title", ""))})
        return bookmarks

    def set_bookmarks(self, path: str, items: list[dict]) -> None:
        """Store the bookmark list for a document, keyed by its resolved path."""
        value = self.get("bookmarks", {})
        if not isinstance(value, dict):
            value = {}
        key = str(Path(path).expanduser().resolve())
        clean: list[dict] = []
        for item in items:
            if not isinstance(item, dict) or "page" not in item:
                continue
            try:
                page = int(item["page"])
            except (TypeError, ValueError):
                continue
            clean.append({"page": page, "title": str(item.get("title", ""))})
        if clean:
            value[key] = clean
        else:
            value.pop(key, None)
        self.set("bookmarks", value)


class RecentFilesManager:
    """Compatibility facade for older callers."""

    def __init__(self, config_file: str | None = None):
        self._settings = SettingsManager(config_file)

    def add(self, file_path: str) -> None:
        self._settings.add_recent_file(file_path)

    def remove(self, file_path: str) -> None:
        values = [item for item in self._settings.recent_files() if item != file_path]
        self._settings.set("recent_files", values)

    def get_all(self) -> list[str]:
        return self._settings.recent_files()

    def get_last(self) -> str | None:
        values = self.get_all()
        return values[0] if values else None

    def clear(self) -> None:
        self._settings.set("recent_files", [])
