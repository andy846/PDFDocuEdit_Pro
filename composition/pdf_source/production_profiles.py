"""Source-free association of detection rules and existing overlay objects."""

from __future__ import annotations

import copy
import json
import shutil
import uuid
from pathlib import Path

from composition.overlay.model import EnvelopeSpec
from composition.overlay.serializer import _references
from composition.template.model import CompositionError
from composition.template.serializer import file_hash
from core.io_atomic import atomic_output
from core.output_safety import contained_path

from .profile_library import identifier
from .profile_library import validate_profile as validate_detection

MAX_BYTES = 5 * 1024 * 1024
MAX_ASSET_BYTES = 100 * 1024 * 1024
KEYS = {
    "kind",
    "schema_version",
    "profile_id",
    "name",
    "description",
    "revision",
    "detection_profile",
    "layout",
}


def validate_profile(raw):
    if (
        not isinstance(raw, dict)
        or set(raw) != KEYS
        or raw.get("kind") != "customer_production"
        or type(raw.get("schema_version")) is not int
        or raw["schema_version"] != 1
    ):
        raise CompositionError("Unsupported customer production profile schema.")
    identifier(raw["profile_id"])
    if (
        not isinstance(raw["name"], str)
        or not 1 <= len(raw["name"].strip()) <= 120
        or not isinstance(raw["description"], str)
        or len(raw["description"]) > 2000
        or type(raw["revision"]) is not int
        or not 1 <= raw["revision"] <= 1000000
    ):
        raise CompositionError("Invalid customer production profile metadata.")
    detection = validate_detection(raw["detection_profile"], for_scan=True)
    layout = raw["layout"]
    if (
        not isinstance(layout, dict)
        or set(layout) != {"objects", "required_scope"}
        or not isinstance(layout["objects"], list)
        or len(layout["objects"]) > 200
    ):
        raise CompositionError("Customer layouts contain at most 200 existing overlay objects.")
    # Validate with the real project model, without opening a PDF or calculating a
    # separate sequence. This synthetic source is never saved in the profile.
    spec = {
        "project_kind": "pdf_overlay",
        "overlay_version": 9,
        "name": raw["name"],
        "source": {
            "path": "profile-validation.pdf",
            "sha256": "0" * 64,
            "size": 1,
            "mtime_ns": 0,
            "pages": 100000,
            "geometry_mode": "uniform",
            "geometries": [{"width_pt": 595, "height_pt": 842, "rotation": 0}],
        },
        "settings": {"pages_per_envelope": 1},
        "objects": layout["objects"],
        "required_scope": layout["required_scope"],
        "detection_review": {"required": True, "accepted": False, "profile": detection},
    }
    EnvelopeSpec.from_dict(spec)
    if len(json.dumps(raw, ensure_ascii=False).encode("utf-8")) > MAX_BYTES:
        raise CompositionError("Customer production profile exceeds 5 MB.")
    return copy.deepcopy(raw)


def from_spec(spec, *, name, description="", revision=1, profile_id=None):
    if spec.detection_review.get("report_version") == 3:
        from .classification import load_report

        detection = load_report(spec.detection_review)["profile"]
    else:
        detection = spec.detection_review.get("profile")
    if not detection:
        raise CompositionError("Choose and scan a reusable detection profile before saving customer layouts.")
    return validate_profile(
        {
            "kind": "customer_production",
            "schema_version": 1,
            "profile_id": profile_id or uuid.uuid4().hex,
            "name": name,
            "description": description,
            "revision": revision,
            "detection_profile": detection,
            "layout": {"objects": spec.to_dict()["objects"], "required_scope": spec.required_scope},
        }
    )


def export_profile(path, value):
    value = validate_profile(value)
    target = Path(path).absolute().with_suffix(".pdpp")
    assets = target.parent / (target.stem + ".assets")
    for owner, key, font in _references({"objects": value["layout"]["objects"]}):
        if not owner[key]:
            continue
        source = Path(owner[key]).resolve()
        if source.stat().st_size > MAX_ASSET_BYTES:
            raise CompositionError("A production profile asset exceeds 100 MB.")
        if font:
            from composition.engine.fonts import load_font
            from composition.template.model import FontSpec

            load_font(FontSpec(**owner))
        digest = file_hash(source)
        copied = contained_path(assets, digest + source.suffix.lower())
        if not copied.exists():
            with atomic_output(copied, overwrite=False) as temporary:
                shutil.copyfile(source, temporary)
                if file_hash(temporary) != digest:
                    raise CompositionError("Profile asset changed during export.")
        elif file_hash(copied) != digest:
            raise CompositionError("Existing production profile asset changed.")
        owner[key] = copied.relative_to(target.parent).as_posix()
    payload = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
    if len(payload) > MAX_BYTES:
        raise CompositionError("Customer production profile exceeds 5 MB.")
    with atomic_output(target) as temporary:
        temporary.write_bytes(payload)
    return target


def read_profile(path):
    path = Path(path)
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise CompositionError("Linked production profiles are not supported.")
    try:
        with path.open("rb") as stream:
            payload = stream.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            raise CompositionError("Customer production profile exceeds 5 MB.")
        value = validate_profile(json.loads(payload))
        for owner, key, _font in _references({"objects": value["layout"]["objects"]}):
            name = owner[key]
            if not name:
                continue
            raw = Path(name)
            if raw.is_absolute():
                raise CompositionError("Production profile assets must be relative and contained.")
            asset = contained_path(path.absolute().parent, *raw.parts)
            if (
                not asset.is_file()
                or asset.stat().st_size > MAX_ASSET_BYTES
                or asset.stem != file_hash(asset)
            ):
                raise CompositionError("Production profile asset is missing or changed.")
            owner[key] = str(asset)
        return value
    except (OSError, KeyError, TypeError, ValueError, RecursionError) as exc:
        if isinstance(exc, CompositionError):
            raise
        raise CompositionError("Invalid customer production profile.") from exc


def apply_profile(spec, value):
    value = validate_profile(value)
    raw = spec.to_dict()
    raw["overlay_version"] = 9
    raw["customer_profile"] = {key: value[key] for key in ("profile_id", "name", "revision")}
    raw["objects"] = value["layout"]["objects"]
    raw["required_scope"] = value["layout"]["required_scope"]
    # Recognition rules are reusable; the previous job's acceptance never is.
    raw["settings"]["pages_per_envelope"] = 1
    raw["settings"]["groups"] = []
    raw["settings"]["excluded_pages"] = []
    raw["detection_review"] = {"required": True, "accepted": False, "profile": value["detection_profile"]}
    return EnvelopeSpec.from_dict(raw)
