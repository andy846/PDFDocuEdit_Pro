"""Installed outline font catalogue and exact-face export; no Qt."""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

from composition.template.model import CompositionError
from core.io_atomic import atomic_output
from core.system_fonts import font_platform_label


def installed_font_files():
    """Discover machine/per-user registered fonts, including nonstandard locations."""
    if sys.platform == "darwin":
        from core.system_fonts import _font_files
        return list(_font_files())
    if os.name != "nt":
        return []
    import winreg
    folders = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
               Path(os.environ.get("LOCALAPPDATA", ".")) / "Microsoft/Windows/Fonts"]
    found = {path.resolve() for folder in folders if folder.is_dir()
             for path in folder.iterdir() if path.is_file()}
    key_name = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
    for hive, folder in ((winreg.HKEY_LOCAL_MACHINE, folders[0]),
                         (winreg.HKEY_CURRENT_USER, folders[1])):
        try:
            with winreg.OpenKey(hive, key_name) as key:
                index = 0
                while True:
                    try:
                        _name, value, _kind = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    index += 1
                    if isinstance(value, str):
                        path = Path(os.path.expandvars(value))
                        found.add((path if path.is_absolute() else folder / path).resolve())
        except OSError:
            pass
    return sorted((path for path in found if path.is_file() and
                   path.suffix.lower() in {".ttf", ".otf", ".ttc", ".otc", ".fon", ".fnt"}), key=lambda p: str(p).casefold())


def _names(font, identifiers):
    values = []
    if "name" not in font:
        return values
    for identifier in identifiers:
        entries = sorted((entry for entry in font["name"].names if entry.nameID == identifier),
                         key=lambda entry: (entry.langID != 0x409, entry.platformID != 3))
        for entry in entries:
            try:
                value = entry.toUnicode().strip()
            except (UnicodeError, LookupError):
                continue
            if value and value not in values:
                values.append(value[:200])
    return values


def _metadata(font, source, index):
    families = _names(font, (16, 1)) or [source.stem]
    styles = _names(font, (17, 2)) or ["Regular"]
    flags = int(getattr(font.get("OS/2"), "fsType", 0))
    outline = "glyf" in font or "CFF " in font or "CFF2" in font
    note = ""
    if flags & (0x0002 | 0x0200):
        note = "This face does not permit outline embedding."
    elif not outline:
        note = "This face has no supported PDF outline glyphs."
    elif any(table in font for table in ("COLR", "CBDT", "sbix", "SVG ")):
        note = "Colour glyphs may be rendered as monochrome outlines."
    return {"family": families[0], "aliases": families, "style": styles[0],
            "source": str(source), "index": index, "axes": {},
            "usable": outline and not bool(flags & (0x0002 | 0x0200)), "note": note}


def inspect_font_file(source):
    path = Path(source).expanduser().resolve()
    if path.stat().st_size > 256 * 1024 * 1024:
        raise CompositionError("System font source is larger than 256 MB.")
    with path.open("rb") as stream:
        signature = stream.read(4)
        if signature == b"ttcf":
            stream.read(4)
            count = int.from_bytes(stream.read(4), "big")
        else:
            count = 1
    if not 1 <= count <= 128:
        raise CompositionError("Invalid font collection face count.")
    faces = []
    for index in range(count):
        with TTFont(path, fontNumber=index, lazy=True) as font:
            face = _metadata(font, path, index)
            faces.append(face)
            if "fvar" in font:
                for instance in font["fvar"].instances:
                    styles = _names(font, (instance.subfamilyNameID,))
                    if styles:
                        variant = {**face, "style": styles[0],
                                   "axes": {str(key): float(value)
                                            for key, value in instance.coordinates.items()}}
                        if variant["style"] != face["style"]:
                            faces.append(variant)
    return faces


def font_catalogue(progress=None, is_cancelled=None):
    paths = installed_font_files()
    faces, unsupported = [], []
    for index, path in enumerate(paths, 1):
        if is_cancelled and is_cancelled():
            raise CompositionError("Font loading cancelled.")
        try:
            faces.extend(inspect_font_file(path))
        except Exception:
            unsupported.append(path.name)
        if progress and index % 20 == 0:
            progress(index, len(paths), f"Loading {font_platform_label()} font families and styles")
    return {"faces": faces, "unsupported": unsupported, "files": len(paths)}


def export_face(face, directory):
    """Extract a TTC/variable face to an embeddable standalone font snapshot."""
    source = Path(face["source"]).expanduser().resolve()
    index = face.get("index", 0)
    axes = face.get("axes", {})
    if type(index) is not int or not 0 <= index < 128 or not isinstance(axes, dict):
        raise CompositionError("Invalid font face selection.")
    if source.stat().st_size > 256 * 1024 * 1024:
        raise CompositionError("System font source is larger than 256 MB.")
    with TTFont(source, fontNumber=index, lazy=False) as font:
        metadata = _metadata(font, source, index)
        if not metadata["usable"]:
            raise CompositionError(metadata["note"])
        if "fvar" in font:
            from fontTools.varLib.instancer import instantiateVariableFont
            defaults = {axis.axisTag: axis.defaultValue for axis in font["fvar"].axes}
            if set(axes) - set(defaults):
                raise CompositionError("Unknown variable font axis.")
            for axis in font["fvar"].axes:
                value = axes.get(axis.axisTag, axis.defaultValue)
                if type(value) not in (int, float) or not math.isfinite(value) or not axis.minValue <= value <= axis.maxValue:
                    raise CompositionError("Invalid variable font axis value.")
            defaults.update(axes)
            font = instantiateVariableFont(font, defaults, inplace=True)
            style = face.get("style", metadata["style"])
            for entry in font["name"].names:
                if entry.nameID in (2, 17):
                    entry.string = style.encode(entry.getEncoding())
                elif entry.nameID == 4:
                    entry.string = (metadata["family"] + " " + style).encode(entry.getEncoding())
        elif axes:
            raise CompositionError("That font is not variable.")
        stat = source.stat()
        key = hashlib.sha256(json.dumps(
            [str(source), stat.st_size, stat.st_mtime_ns, index, axes, face.get("style")], sort_keys=True,
        ).encode("utf-8")).hexdigest()[:24]
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        suffix = ".otf" if "CFF " in font or "CFF2" in font else ".ttf"
        target = directory / (key + suffix)
        if not target.exists():
            with atomic_output(target, overwrite=False) as staged:
                font.save(staged)
    return {"file": str(target), "family": face.get("family", metadata["family"]),
            "style": face.get("style", metadata["style"]), "note": metadata["note"]}
