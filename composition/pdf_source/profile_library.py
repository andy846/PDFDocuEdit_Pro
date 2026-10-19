"""Versioned, source-free detection collections; legacy .pdmp stays unchanged."""

from __future__ import annotations

import copy
import json
import os
import re
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from itertools import islice
from pathlib import Path

from composition.template.model import CompositionError
from core.io_atomic import atomic_output
from core.output_safety import contained_path

from .detection import DetectionConfig
from .profiles import _validate_profile_config, load_profile, save_profile

MAX_BYTES = 1024 * 1024
MAX_RULES = 16
MAX_PROFILES = 300
MAX_REVISIONS = 1000
_WRITE_LOCK = ".library-write.lock"


def profile_name_key(name):
    """Compare user-visible names without changing their stored spelling."""
    return unicodedata.normalize("NFKC", name).strip().casefold()


def is_single_profile(value):
    return isinstance(value, dict) and value.get("kind") == "single_mailpiece_detection"


def new_single_profile(config, *, name=None, profile_id=None, revision=1):
    """Runtime library metadata; disk/export retains the existing .pdmp schema."""
    return validate_single_profile({
        "kind": "single_mailpiece_detection", "profile_id": profile_id or uuid.uuid4().hex,
        "name": name or config.get("profile_name") or "Detection profile", "description": "",
        "revision": revision, "config": copy.deepcopy(config),
    })


def validate_single_profile(raw):
    if not is_single_profile(raw) or set(raw) != {"kind", "profile_id", "name", "description", "revision", "config"}:
        raise CompositionError("Invalid single-rule library profile.")
    identifier(raw["profile_id"])
    _text(raw["name"], 120)
    if raw["description"] != "" or type(raw["revision"]) is not int or not 1 <= raw["revision"] <= MAX_REVISIONS:
        raise CompositionError("Invalid single-rule profile metadata.")
    try:
        config = DetectionConfig(**raw["config"])
    except TypeError as exc:
        raise CompositionError("Invalid single-rule detection configuration.") from exc
    _validate_profile_config(config)
    config.profile_name = raw["name"]
    return {**copy.deepcopy(raw), "config": asdict(config)}


def validate_library_profile(value, *, for_scan=False):
    return validate_single_profile(value) if is_single_profile(value) else validate_profile(value, for_scan=for_scan)


def export_library_profile(path, value):
    if is_single_profile(value):
        checked = validate_single_profile(value)
        return save_profile(path, DetectionConfig(**checked["config"]))
    return export_profile(path, value)


def _text(value, maximum, *, empty=False):
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or (not empty and not value.strip())
        or any(ord(c) < 32 and c not in "\n\t" for c in value)
    ):
        raise CompositionError("Invalid profile text.")


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise CompositionError("Invalid profile / template / rule identity.")
    return value


def new_profile(name):
    return {
        "kind": "mailpiece_detection",
        "schema_version": 1,
        "profile_id": uuid.uuid4().hex,
        "name": name,
        "description": "",
        "revision": 1,
        "rule_sets": [],
    }


def new_rule(name, config, *, template_id=None, primary=None):
    kinds = {r["kind"] for r in config["rules"]}
    return {
        "rule_id": uuid.uuid4().hex,
        "template_id": template_id or uuid.uuid4().hex,
        "name": name,
        "primary": primary or ("first_text" if "first_text" in kinds else "page_number"),
        "config": copy.deepcopy(config),
    }


def validate_profile(raw, *, for_scan=False):
    keys = {"kind", "schema_version", "profile_id", "name", "description", "revision", "rule_sets"}
    if (
        not isinstance(raw, dict)
        or set(raw) != keys
        or raw["kind"] != "mailpiece_detection"
        or type(raw["schema_version"]) is not int
        or raw["schema_version"] != 1
    ):
        raise CompositionError("Unsupported mailpiece collection schema.")
    identifier(raw["profile_id"])
    _text(raw["name"], 120)
    _text(raw["description"], 2000, empty=True)
    if type(raw["revision"]) is not int or not 1 <= raw["revision"] <= MAX_REVISIONS:
        raise CompositionError("Invalid profile revision.")
    rules = raw["rule_sets"]
    if not isinstance(rules, list) or not int(for_scan) <= len(rules) <= MAX_RULES:
        raise CompositionError("A scan requires 1 to 16 rule sets; empty profiles are drafts.")
    seen = set()
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != {"rule_id", "template_id", "name", "primary", "config"}:
            raise CompositionError("Invalid source-free rule set.")
        key = identifier(rule["rule_id"])
        identifier(rule["template_id"])
        _text(rule["name"], 120)
        if key in seen:
            raise CompositionError("Duplicate rule identity.")
        seen.add(key)
        try:
            config = DetectionConfig(**rule["config"])
            config.validate()
        except (TypeError, KeyError) as exc:
            raise CompositionError("Invalid detection configuration.") from exc
        if config.version != 2 or rule["primary"] not in {"first_text", "page_number"}:
            raise CompositionError("Use spatial v2 rules and a marker or page restart as primary evidence.")
        if rule["primary"] not in {r["kind"] for r in config.rules}:
            raise CompositionError("The primary signal must be configured.")
    value = copy.deepcopy(raw)
    if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_BYTES:
        raise CompositionError("Mailpiece profile exceeds 1 MB.")
    return value


def read_profile(path):
    path = Path(path)
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise CompositionError("Linked profiles are not supported.")
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise CompositionError("Mailpiece profile exceeds 1 MB.")
        if path.suffix.lower() == ".pdmp":
            from .profiles import load_profile

            config = load_profile(path)
            value = new_profile(config.get("profile_name") or path.stem[:120])
            value["rule_sets"] = [new_rule("Imported rule", config, template_id="LETTER")]
            return validate_profile(value)
        return validate_profile(json.loads(data.decode("utf-8-sig")))
    except (ValueError, TypeError, RecursionError) as exc:
        if isinstance(exc, CompositionError):
            raise
        raise CompositionError("Invalid detection profile.") from exc


def export_profile(path, profile):
    value = validate_profile(profile)
    target = Path(path).with_suffix(".pdmpx")
    with atomic_output(target) as temporary:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


class ProfileLibrary:
    def __init__(self, root):
        self.root = Path(root)

    @contextmanager
    def _writing(self):
        """Serialize name checks and writes across windows/processes, without waiting."""
        self.root.mkdir(parents=True, exist_ok=True)
        path = contained_path(self.root, _WRITE_LOCK)
        # Keep the lock file: unlinking it could let POSIX writers lock different inodes.
        with path.open("a+b") as stream:
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise CompositionError("Profile library is busy; try saving again.") from exc
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _check_name(self, value, current=None):
        key = profile_name_key(value["name"])
        # Historical duplicates remain editable by explicit identity. A rename or
        # new identity must not introduce another collision.
        if current and profile_name_key(current["name"]) == key:
            return
        if any(entry["profile_id"] != value["profile_id"] and profile_name_key(entry["name"]) == key
               for entry in self.list()["entries"]):
            raise CompositionError(
                "A profile with this name already exists. Select it to save a new revision, or choose another name."
            )

    def _files(self, profile_id):
        folder = contained_path(self.root, identifier(profile_id))
        if not folder.exists():
            return []
        paths = list(islice(folder.glob("r*.pdmp*"), MAX_REVISIONS + 1))
        if len(paths) > MAX_REVISIONS:
            raise CompositionError("Profile revision limit reached.")
        if any(not re.fullmatch(r"r[0-9]{6}\.pdmpx?", p.name) for p in paths):
            raise CompositionError("Invalid profile revision filename.")
        if len({p.suffix for p in paths}) > 1:
            raise CompositionError("Profile revisions cannot mix single-rule and collection formats.")
        return sorted(paths)

    def read(self, profile_id, revision=None):
        paths = self._files(profile_id)
        if not paths:
            raise FileNotFoundError("Profile is not in the library.")
        if revision is not None and (type(revision) is not int or not 1 <= revision <= MAX_REVISIONS):
            raise CompositionError("Invalid profile revision.")
        path = contained_path(self.root, profile_id, paths[-1].name if revision is None else f"r{revision:06d}{paths[-1].suffix}")
        if path.suffix == ".pdmp":
            return new_single_profile(load_profile(path), profile_id=profile_id, revision=int(path.stem[1:]))
        value = read_profile(path)
        if value["profile_id"] != profile_id or path.stem != f"r{value['revision']:06d}":
            raise CompositionError("Profile revision identity changed.")
        return value

    def list(self, *, is_cancelled=lambda: False):
        entries, errors = [], []
        if not self.root.exists():
            return {"entries": entries, "errors": errors}
        folders = list(islice((p for p in self.root.iterdir() if p.name != _WRITE_LOCK), MAX_PROFILES + 1))
        if len(folders) > MAX_PROFILES:
            errors.append("Library exceeds 300 profiles.")
        for folder in folders[:MAX_PROFILES]:
            if is_cancelled():
                break
            try:
                value = self.read(folder.name)
                entries.append({key: value[key] for key in ("profile_id", "name", "description", "revision")}
                               | {"rule_count": 1 if is_single_profile(value) else len(value["rule_sets"]),
                                  "kind": value["kind"]})
            except (OSError, ValueError, CompositionError) as exc:
                errors.append(f"{folder.name}: {exc}")
        entries.sort(key=lambda item: (profile_name_key(item["name"]), item["profile_id"]))
        return {"entries": entries, "errors": errors}

    def save(self, profile):
        with self._writing():
            return self._save(profile)

    def _save(self, profile):
        value = validate_library_profile(profile)
        paths = self._files(value["profile_id"])
        current = None
        if paths:
            current = self.read(value["profile_id"])
            if current["revision"] != value["revision"] or current["kind"] != value["kind"]:
                raise CompositionError("Profile revision changed; reopen before saving.")
            value["revision"] += 1
        elif value["revision"] != 1:
            raise CompositionError("New profiles start at revision 1.")
        if not paths and len(self.list()["entries"]) >= MAX_PROFILES:
            raise CompositionError("Library limit is 300 profiles.")
        self._check_name(value, current)
        value = validate_library_profile(value)
        suffix = ".pdmp" if is_single_profile(value) else ".pdmpx"
        target = contained_path(self.root, value["profile_id"], f"r{value['revision']:06d}{suffix}")
        try:
            if is_single_profile(value):
                save_profile(target, DetectionConfig(**value["config"]), overwrite=False)
            else:
                with atomic_output(target, overwrite=False) as temporary:
                    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        except FileExistsError as exc:
            raise CompositionError("Profile revision changed; reopen before saving.") from exc
        return value

    def add_single(self, config, *, profile_id=None, revision=None, is_cancelled=lambda: False):
        if is_cancelled():
            raise CompositionError("Profile save cancelled.")
        with self._writing():
            return self._add_single(config, profile_id=profile_id, revision=revision, is_cancelled=is_cancelled)

    def _add_single(self, config, *, profile_id=None, revision=None, is_cancelled=lambda: False):
        value = new_single_profile(config)
        if profile_id:
            current = self.read(profile_id)
            if not is_single_profile(current) or current["revision"] != revision:
                raise CompositionError("Profile revision changed; reopen before saving.")
            if profile_name_key(current["name"]) == profile_name_key(value["name"]):
                value.update(profile_id=profile_id, revision=revision)
                if is_cancelled():
                    raise CompositionError("Profile save cancelled.")
                return current if current == value else self._save(value)
        identical = []
        for entry in self.list(is_cancelled=is_cancelled)["entries"]:
            if is_cancelled():
                raise CompositionError("Profile save cancelled.")
            if entry["kind"] == "single_mailpiece_detection" and entry["name"] == value["name"]:
                saved = self.read(entry["profile_id"])
                if saved["config"] == value["config"]:
                    identical.append(saved)
        if is_cancelled():
            raise CompositionError("Profile save cancelled.")
        if len(identical) == 1:
            return identical[0]
        return self._save(value)

    def rename(self, profile_id, name):
        value = self.read(profile_id)
        value["name"] = name
        return self.save(value)

    def duplicate(self, profile_id, name):
        value = self.read(profile_id)
        value.update(profile_id=uuid.uuid4().hex, name=name, revision=1)
        return self.save(value)

    def import_profile(self, path):
        with self._writing():
            return self._import_profile(path)

    def _import_profile(self, path):
        if Path(path).suffix.lower() == ".pdmp":
            # Collections retain their existing v2 import contract; v1 stays single.
            checked_path = Path(path)
            if checked_path.is_symlink() or getattr(checked_path, "is_junction", lambda: False)():
                raise CompositionError("Linked profiles are not supported.")
            config = load_profile(path)
            if config["version"] == 1:
                config["profile_name"] = config.get("profile_name") or checked_path.stem[:120]
                return self._add_single(config)
        value = read_profile(path)
        target = contained_path(self.root, value["profile_id"], f"r{value['revision']:06d}.pdmpx")
        if target.exists():
            if read_profile(target) != value:
                raise CompositionError(
                    "Imported profile conflicts with an existing revision. Duplicate it first."
                )
            return value
        paths = self._files(value["profile_id"])
        if not paths and len(self.list()["entries"]) >= MAX_PROFILES:
            raise CompositionError("Library profile limit reached.")
        if len(paths) >= MAX_REVISIONS:
            raise CompositionError("Profile revision limit reached.")
        # Importing an older snapshot cannot change the current displayed name.
        current = self.read(value["profile_id"]) if paths else None
        if current is None or value["revision"] > current["revision"]:
            self._check_name(value, current)
        # Imported revision numbers are preserved, including historical snapshots.
        with atomic_output(target, overwrite=False) as temporary:
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        return value
