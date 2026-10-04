"""Readable envelope projects, atomic saving and licensed content-addressed assets."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from composition.engine.fonts import load_font
from composition.template.serializer import file_hash
from core.io_atomic import atomic_output

from .model import EnvelopeSpec


def _references(value):
    for obj in value["objects"]:
        element = obj["element"]
        yield element, "image", False
        yield element["font"], "file", True
        for font in element["glyph_repairs"].values():
            yield font, "file", True
        variant = element["rules"].get("alternative")
        if variant:
            yield variant, "image", False


def save_project(spec, path):
    spec.validate()
    target = Path(path).resolve().with_suffix(".pdcx")
    value = spec.to_dict()
    assets = target.parent / (target.stem+".assets")
    for owner, key, font in _references(value):
        raw = owner[key]
        if not raw:
            continue
        source = Path(raw).resolve()
        if font:
            from composition.template.model import FontSpec
            load_font(FontSpec(**owner))
        assets.mkdir(parents=True, exist_ok=True)
        copied = assets / (file_hash(source)[:20]+source.suffix.lower())
        if not copied.exists():
            with atomic_output(copied, overwrite=False) as temp:
                shutil.copyfile(source, temp)
        owner[key] = copied.relative_to(target.parent).as_posix()
    source = Path(value["source"]["path"]).resolve()
    if spec.source_link.get("managed"):
        from composition.template.model import CompositionError
        digest = file_hash(source)
        if digest != spec.source.sha256:
            raise CompositionError("Managed source changed; review and update it before saving the project.")
        assets.mkdir(parents=True, exist_ok=True)
        copied = assets / (digest[:20] + ".pdf")
        if copied.exists() and file_hash(copied) != digest:
            raise CompositionError("Saved source asset changed. Choose a new project location or repair the asset.")
        if source != copied and not copied.exists():
            with atomic_output(copied, overwrite=False) as temp:
                shutil.copyfile(source, temp)
        source = copied
        # Copying changes filesystem timestamps; keep the saved SourceInfo current.
        value["source"]["size"] = source.stat().st_size
        value["source"]["mtime_ns"] = source.stat().st_mtime_ns
    try:
        value["source"]["path"] = source.relative_to(target.parent).as_posix()
    except ValueError:
        value["source"]["path"] = str(source)
    with atomic_output(target) as temp:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return target


def load_project(path):
    source = Path(path).resolve()
    if source.stat().st_size > 10*1024*1024:
        from composition.template.model import CompositionError
        raise CompositionError("Overlay project exceeds 10 MB.")
    value = json.loads(source.read_text(encoding="utf-8"))
    # Validate the declarative structure before traversing asset references.
    value = EnvelopeSpec.from_dict(value).to_dict()
    for owner, key, _font in _references(value):
        if owner[key]:
            owner[key] = str((source.parent / owner[key]).resolve())
    value["source"]["path"] = str((source.parent / value["source"]["path"]).resolve())
    return EnvelopeSpec.from_dict(value)
