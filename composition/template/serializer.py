"""Readable project JSON with content-addressed static assets."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from core.io_atomic import atomic_output

from .model import CompositionError, Template, validate_template


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save_project(template: Template, path: str | Path) -> Path:
    target = Path(path).expanduser().resolve()
    if target.suffix.lower() != ".pdcx":
        target = target.with_suffix(".pdcx")
    validate_template(template)
    value = template.to_dict()
    assets = target.parent / f"{target.stem}.assets"

    def store_asset(raw: str) -> str:
        if not raw:
            return ""
        source = Path(raw).resolve()
        if not source.is_file():
            raise CompositionError(f"Asset not found: {source}")
        assets.mkdir(parents=True, exist_ok=True)
        copied = assets / f"{file_hash(source)[:20]}{source.suffix.lower()}"
        if source != copied and not copied.exists():
            with atomic_output(copied, overwrite=False) as staged:
                shutil.copyfile(source, staged)
        return copied.relative_to(target.parent).as_posix()

    for page in value["pages"]:
        page["background"] = store_asset(page["background"])
    for element in (element for page in value["pages"] for element in page["elements"]):
        element["image"] = store_asset(element["image"])
        if element["rules"]["alternative"]:
            variant = element["rules"]["alternative"]
            variant["image"] = store_asset(variant["image"])
        # Custom fonts are copied only after font embedding permissions are checked.
        if element["font"]["file"]:
            from composition.engine.fonts import load_font

            from .model import FontSpec

            load_font(FontSpec(**element["font"]))
            element["font"]["file"] = store_asset(element["font"]["file"])
        for spec in element["glyph_repairs"].values():
            from composition.engine.fonts import load_font

            from .model import FontSpec
            load_font(FontSpec(**spec))
            spec["file"] = store_asset(spec["file"])
    if value["data"]["path"]:
        source = Path(value["data"]["path"]).resolve()
        try:
            value["data"]["path"] = source.relative_to(target.parent).as_posix()
        except ValueError:
            value["data"]["path"] = str(source)
    with atomic_output(target) as staged:
        staged.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def load_project(path: str | Path) -> Template:
    source = Path(path).expanduser().resolve()
    if source.stat().st_size > 10 * 1024 * 1024:
        raise CompositionError("The project JSON is larger than 10 MB.")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
        template = Template.from_dict(value)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CompositionError(f"Invalid project JSON: {exc}") from exc

    def resolve(raw: str) -> str:
        if not raw:
            return ""
        # Project assets can be relative; paths are inert references, never commands.
        path = Path(raw).expanduser()
        return str((path if path.is_absolute() else source.parent / path).resolve())

    for page in template.pages:
        page.background = resolve(page.background)
    template.data.path = resolve(template.data.path)
    for element in template.all_elements():
        element.image = resolve(element.image)
        if element.rules.alternative:
            element.rules.alternative.image = resolve(element.rules.alternative.image)
        element.font.file = resolve(element.font.file)
        for spec in element.glyph_repairs.values():
            spec.file = resolve(spec.file)
    return template
