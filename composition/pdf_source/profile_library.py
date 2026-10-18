"""Versioned, source-free detection collections; legacy .pdmp stays unchanged."""

from __future__ import annotations

import copy
import json
import re
import uuid
from itertools import islice
from pathlib import Path

from composition.template.model import CompositionError
from core.io_atomic import atomic_output
from core.output_safety import contained_path

from .detection import DetectionConfig

MAX_BYTES = 1024 * 1024
MAX_RULES = 16
MAX_PROFILES = 300
MAX_REVISIONS = 1000


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

    def _files(self, profile_id):
        folder = contained_path(self.root, identifier(profile_id))
        if not folder.exists():
            return []
        paths = list(islice(folder.glob("r*.pdmpx"), MAX_REVISIONS + 1))
        if len(paths) > MAX_REVISIONS:
            raise CompositionError("Profile revision limit reached.")
        if any(not re.fullmatch(r"r[0-9]{6}\.pdmpx", p.name) for p in paths):
            raise CompositionError("Invalid profile revision filename.")
        return sorted(paths)

    def read(self, profile_id, revision=None):
        paths = self._files(profile_id)
        if not paths:
            raise FileNotFoundError("Profile is not in the library.")
        path = (
            paths[-1] if revision is None else contained_path(self.root, profile_id, f"r{revision:06d}.pdmpx")
        )
        value = read_profile(path)
        if value["profile_id"] != profile_id or path.stem != f"r{value['revision']:06d}":
            raise CompositionError("Profile revision identity changed.")
        return value

    def list(self, *, is_cancelled=lambda: False):
        entries, errors = [], []
        if not self.root.exists():
            return {"entries": entries, "errors": errors}
        folders = list(islice(self.root.iterdir(), MAX_PROFILES + 1))
        if len(folders) > MAX_PROFILES:
            errors.append("Library exceeds 300 profiles.")
        for folder in folders[:MAX_PROFILES]:
            if is_cancelled():
                break
            try:
                value = self.read(folder.name)
                entries.append(value)
            except (OSError, ValueError, CompositionError) as exc:
                errors.append(f"{folder.name}: {exc}")
        entries.sort(key=lambda item: item["name"].casefold())
        return {"entries": entries, "errors": errors}

    def save(self, profile):
        value = validate_profile(profile)
        paths = self._files(value["profile_id"])
        if paths:
            current = self.read(value["profile_id"])
            if current["revision"] != value["revision"]:
                raise CompositionError("Profile revision changed; reopen before saving.")
            value["revision"] += 1
        elif value["revision"] != 1:
            raise CompositionError("New profiles start at revision 1.")
        if not paths and len(self.list()["entries"]) >= MAX_PROFILES:
            raise CompositionError("Library limit is 300 profiles.")
        value = validate_profile(value)
        target = contained_path(self.root, value["profile_id"], f"r{value['revision']:06d}.pdmpx")
        try:
            with atomic_output(target, overwrite=False) as temporary:
                temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        except FileExistsError as exc:
            raise CompositionError("Profile revision changed; reopen before saving.") from exc
        return value

    def rename(self, profile_id, name):
        value = self.read(profile_id)
        value["name"] = name
        return self.save(value)

    def duplicate(self, profile_id, name):
        value = self.read(profile_id)
        value.update(profile_id=uuid.uuid4().hex, name=name, revision=1)
        return self.save(value)

    def import_profile(self, path):
        value = read_profile(path)
        target = contained_path(self.root, value["profile_id"], f"r{value['revision']:06d}.pdmpx")
        if target.exists():
            if read_profile(target) != value:
                raise CompositionError(
                    "Imported profile conflicts with an existing revision. Duplicate it first."
                )
            return value
        # Imported revision numbers are preserved, including historical snapshots.
        with atomic_output(target, overwrite=False) as temporary:
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        return value
