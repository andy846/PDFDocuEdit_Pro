"""Bounded .app ZIPs preserving only validated internal relative symlinks."""
from __future__ import annotations

import os
import posixpath
import shutil
import stat
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath

from .protocol import CHUNK, MAX_FILES, UpdateError

APP = "PDFDocuEdit Pro.app"


def bundle_members(archive, expanded_size):
    members = archive.infolist()
    if len(members) > MAX_FILES or sum(item.file_size for item in members) != expanded_size:
        raise UpdateError("Mac ZIP contents do not match signed size limits.")
    names, links, regular, components = {}, {}, set(), {}
    for item in members:
        name = item.orig_filename.rstrip("/")
        parts = name.split("/")
        mode = item.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if (item.orig_filename != item.filename or not name or parts[0] != APP or
                any(not part or part in {".", ".."} or "\\" in part or ":" in part or
                    any(ord(c) < 32 for c in part) for part in parts) or item.flag_bits & 1 or
                kind not in (0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK)):
            raise UpdateError("Unsafe Mac bundle path or file type.")
        folded = unicodedata.normalize("NFC", name).casefold()
        if folded in names:
            raise UpdateError("Mac ZIP contains duplicate/case-colliding paths.")
        names[folded] = name
        for length in range(1, len(parts) + 1):
            component = "/".join(parts[:length])
            key = unicodedata.normalize("NFC", component).casefold()
            if key in components and components[key] != component:
                raise UpdateError("Mac ZIP contains inconsistent path spelling.")
            components[key] = component
        if kind == stat.S_IFLNK:
            if item.file_size > 4096:
                raise UpdateError("Mac link target exceeds limits.")
            try:
                target = archive.read(item).decode("utf-8")
            except UnicodeError as error:
                raise UpdateError("Invalid Mac link target.") from error
            if not target or target.startswith("/") or "\\" in target or "\x00" in target:
                raise UpdateError("Mac bundle links must be relative.")
            links[name] = target
        elif not item.is_dir():
            regular.add(name)
    for name in names.values():
        if any(parent.as_posix() in links for parent in PurePosixPath(name).parents):
            raise UpdateError("Mac ZIP writes through a symbolic-link directory.")
    # Resolve link chains lexically before creating anything. No writes follow links.
    for name, target in links.items():
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
        seen = {name}
        while True:
            if not resolved.startswith(APP + "/") or resolved in seen:
                raise UpdateError("Mac bundle link escapes the app or creates a cycle.")
            prefixes = [resolved, *[p.as_posix() for p in PurePosixPath(resolved).parents]]
            link = next((p for p in prefixes if p in links), None)
            if link is None:
                if unicodedata.normalize("NFC", resolved).casefold() not in names:
                    raise UpdateError("Mac bundle contains a dangling link.")
                break
            seen.add(resolved)
            suffix = resolved[len(link):].lstrip("/")
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(link), links[link], suffix))
            if len(seen) > 64:
                raise UpdateError("Mac link chain is too long.")
    if f"{APP}/Contents/MacOS/PDFDocuEdit Pro" not in regular or f"{APP}/Contents/Info.plist" not in regular:
        raise UpdateError("Mac ZIP is missing the application executable or Info.plist.")
    return members, links


def extract_bundle(package, destination, expanded_size):
    destination = Path(destination)
    destination.mkdir(parents=False, exist_ok=False)
    try:
        with zipfile.ZipFile(package) as archive:
            members, links = bundle_members(archive, expanded_size)
            for item in members:
                name = item.filename.rstrip("/")
                if name in links:
                    continue
                target = destination.joinpath(*PurePosixPath(name).parts)
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(item) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output, CHUNK)
                    target.chmod((item.external_attr >> 16) & 0o777 or 0o644)
            for name, value in links.items():
                target = destination.joinpath(*PurePosixPath(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(value, target)
    except Exception:
        shutil.rmtree(destination)
        raise


def write_bundle(app, package):
    """Archive the owned sealed .app without dereferencing framework links."""
    app, package = Path(app), Path(package)
    if app.name != APP or app.is_symlink():
        raise UpdateError("Expected an owned PDFDocuEdit Pro.app directory.")
    expanded = 0
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted([app, *app.rglob("*")]):
            name = path.relative_to(app.parent).as_posix()
            if path.is_symlink():
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                value = os.readlink(path).encode("utf-8")
                archive.writestr(info, value)
                expanded += len(value)
            elif path.is_dir():
                archive.write(path, name + "/")
            elif path.is_file():
                archive.write(path, name)
                expanded += path.stat().st_size
            else:
                raise UpdateError("Unsupported file in Mac app.")
    with zipfile.ZipFile(package) as archive:
        bundle_members(archive, expanded)
    return expanded
