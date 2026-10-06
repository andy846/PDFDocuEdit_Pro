"""Local, declarative media profiles. No Qt or customer document storage."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from itertools import islice
from pathlib import Path

from composition.media.model import MediaSpec, PrinterProfile
from core.io_atomic import atomic_output

MAX_BYTES = 1024 * 1024
MAX_IMPORT = 100
MAX_PROFILES = 300


def validate_profile(raw: dict) -> dict:
    if (not isinstance(raw, dict) or set(raw) != {"kind", "profile_version", "settings"}
            or type(raw.get("profile_version")) is not int or raw["profile_version"] not in (1, 2)
            or raw.get("kind") not in ("printer", "media") or not isinstance(raw.get("settings"), dict)):
        raise ValueError("Incorrect profile type / version. Select a media or printer profile JSON.")
    settings = (asdict(PrinterProfile.from_dict(raw["settings"])) if raw["kind"] == "printer"
                else MediaSpec.from_dict(raw["settings"]).to_dict())
    printer = settings if raw["kind"] == "printer" else asdict(PrinterProfile.from_dict(settings["printer_profile"]))
    version = 2 if printer.get("backend") == "postscript" else 1
    if raw["profile_version"] != version:
        raise ValueError("Profile wrapper version does not match its output format.")
    # Normalize optional printer defaults for stable identity across saves.
    defaults = {"name": "", "catalog_id": ""}
    if printer["backend"] == "postscript":
        defaults.update(media_type="", media_color="", media_position=None)
    printer["mappings"] = {key: {**defaults, **item} for key, item in printer["mappings"].items()}
    if raw["kind"] == "media":
        settings["printer_profile"] = printer
    return {"kind": raw["kind"], "profile_version": version, "settings": settings}


def read_profile(path: str | Path) -> dict:
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Profile exceeds 1 MB.")
    return validate_profile(json.loads(data.decode("utf-8-sig")))


def identity(profile: dict) -> str:
    data = json.dumps(profile, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def list_profiles(directory: str | Path, *, is_cancelled=lambda: False) -> dict:
    directory = Path(directory)
    entries, errors, seen = [], [], set()
    if not directory.exists():
        return {"entries": entries, "errors": errors, "cancelled": False}
    paths = sorted(islice(directory.glob("*.json"), MAX_PROFILES + 1))
    if len(paths) > MAX_PROFILES:
        errors.append(f"Library exceeds {MAX_PROFILES} files. Move unused profiles out of this folder.")
    for path in paths[:MAX_PROFILES]:
        if is_cancelled():
            return {"entries": entries, "errors": errors, "cancelled": True}
        try:
            if path.is_symlink():
                raise ValueError("Linked profile files are not supported.")
            profile = read_profile(path)
            key = identity(profile)
            if key in seen:
                continue
            seen.add(key)
            printer = profile["settings"] if profile["kind"] == "printer" else profile["settings"]["printer_profile"]
            entries.append({"id": key, "path": str(path), "name": printer["profile_name"] or "Untitled profile",
                            "family": printer["family"], "backend": printer["backend"], "profile": profile})
        except (ValueError, OSError, TypeError, KeyError, AttributeError, RecursionError) as exc:
            errors.append(f"{path.name}: {exc}")
    entries.sort(key=lambda entry: (entry["name"].casefold(), entry["profile"]["kind"]))
    return {"entries": entries, "errors": errors, "cancelled": False}


def import_profiles(directory: str | Path, sources=(), *, folder=None, is_cancelled=lambda: False,
                    progress=lambda *_: None) -> dict:
    """Commit each valid profile independently; retain prior imports on cancel."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    current = list_profiles(directory, is_cancelled=is_cancelled)
    known = {entry["id"] for entry in current["entries"]}
    errors = []
    imported = duplicates = 0
    paths = list(islice((Path(p) for p in sources), MAX_IMPORT + 1))
    if folder is not None:
        paths = list(islice(Path(folder).rglob("*.json"), MAX_IMPORT + 1))
    if len(paths) > MAX_IMPORT:
        raise ValueError(f"Import at most {MAX_IMPORT} profile files at a time.")
    for index, path in enumerate(paths):
        if is_cancelled():
            break
        try:
            profile = read_profile(path)
            key = identity(profile)
            if key in known:
                duplicates += 1
                continue
            if len(known) >= MAX_PROFILES:
                raise ValueError(f"Library limit is {MAX_PROFILES} profiles.")
            target = directory / ("profile-" + key + ".json")
            if target.exists():
                # Never overwrite a conflicting/corrupt local file.
                if identity(read_profile(target)) != key:
                    raise ValueError("Existing library file has conflicting content.")
                duplicates += 1
            else:
                with atomic_output(target, overwrite=False) as staged:
                    staged.write_text(json.dumps(profile, ensure_ascii=True, indent=2), encoding="utf-8")
                imported += 1
            known.add(key)
        except (ValueError, OSError, TypeError, KeyError, AttributeError, RecursionError) as exc:
            errors.append(f"{path.name}: {exc}")
        finally:
            progress(index + 1, len(paths), "Importing media profiles")
    result = list_profiles(directory, is_cancelled=is_cancelled)
    return {**result, "imported": imported, "duplicates": duplicates, "import_errors": errors}
