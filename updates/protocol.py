"""Signed release metadata, bounded HTTPS downloads and safe ZIP extraction."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

PRODUCT = "PDFDocuEditPro"
EXECUTABLE = "PDFDocuEdit Pro.exe"
LAUNCHER_VERSION = "1.0.0"
MAX_ZIP_BYTES = 2 * 1024**3
MAX_EXPANDED_BYTES = 8 * 1024**3
MAX_FILES = 50000
SPACE_RESERVE = 256 * 1024**2
CHUNK = 1024 * 1024


class UpdateError(Exception):
    """An update could not be safely completed."""


class Cancelled(UpdateError):
    pass


def version(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value):
        raise UpdateError("Invalid stable version number.")
    return tuple(map(int, value.split(".")))


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            name = handle.name
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if name:
            Path(name).unlink(missing_ok=True)


def read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise UpdateError(f"Invalid metadata: {path.name}")
    return data


def digest_file(path: Path, cancelled: Callable[[], bool] = lambda: False) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(CHUNK):
            if cancelled():
                raise Cancelled("Update cancelled.")
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class Manifest:
    version: str
    asset: str
    size: int
    sha256: str
    expanded_size: int

    @classmethod
    def verify(cls, raw: bytes, signature: bytes, public_key_hex: str) -> Manifest:
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex)).verify(signature, raw)
        except (ValueError, InvalidSignature) as exc:
            raise UpdateError("Update signature is invalid. Nothing was installed.") from exc
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("manifest must be an object")
            if (data["schema"], data["product"], data["platform"]) != (1, PRODUCT, "windows-x64"):
                raise UpdateError("This update is not compatible with this application.")
            version(data["version"])
            if version(data["min_launcher_version"]) > version(LAUNCHER_VERSION):
                raise UpdateError("Please manually replace the launcher using the new deployment ZIP first.")
            for key, limit in (("size", MAX_ZIP_BYTES), ("expanded_size", MAX_EXPANDED_BYTES)):
                if type(data[key]) is not int or not 0 < data[key] <= limit:
                    raise UpdateError("Update size exceeds the supported limit.")
            asset = f"PDFDocuEdit-Pro-v{data['version']}-Update-Windows-x64.zip"
            if data["asset"] != asset or not re.fullmatch(r"[0-9a-f]{64}", data["sha256"]):
                raise UpdateError("Invalid update filename or checksum.")
            return cls(data["version"], asset, data["size"], data["sha256"], data["expanded_size"])
        except (KeyError, TypeError, ValueError) as exc:
            raise UpdateError("Invalid update manifest.") from exc

    def verify_archive(self, path: Path, cancelled: Callable[[], bool] = lambda: False) -> None:
        if path.stat().st_size != self.size or digest_file(path, cancelled) != self.sha256:
            raise UpdateError("Update ZIP is incomplete or has an incorrect checksum.")


def _check_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    allowed = {"api.github.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
    if parsed.scheme != "https" or parsed.hostname not in allowed or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise UpdateError("Update download must use an approved GitHub HTTPS address.")


class _HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url: str):
    _check_url(url)
    # urllib uses Windows Internet Settings proxies and the default TLS trust
    # store; no credentials or certificate-verification bypasses are embedded.
    media_type = "application/vnd.github+json" if urllib.parse.urlparse(url).hostname == "api.github.com" else "application/octet-stream"
    request = urllib.request.Request(url, headers={"User-Agent": f"{PRODUCT}-Updater/1", "Accept": media_type})
    return urllib.request.build_opener(_HTTPSRedirect()).open(request, timeout=20)


def fetch_small(url: str, limit: int) -> bytes:
    with _open(url) as response:
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise UpdateError("Release metadata is too large.")
    return raw


@dataclass(frozen=True)
class Release:
    manifest: Manifest
    raw: bytes
    signature: bytes
    url: str
    notes: str


def check_release(repository: str, public_key: str, current: str) -> Release | None:
    if not public_key:
        raise UpdateError("Release signing has not been configured for this build.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise UpdateError("Invalid release repository.")
    try:
        payload = json.loads(fetch_small(f"https://api.github.com/repos/{repository}/releases/latest", 2 * CHUNK))
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            return check_release_direct(repository, public_key, current)
        if exc.code == 404:
            raise UpdateError("No public stable release is available yet.") from exc
        raise
    if payload.get("draft") or payload.get("prerelease"):
        return None
    tag = payload.get("tag_name", "")
    target = tag.removeprefix("v")
    if version(target) <= version(current):
        return None
    assets = {a["name"]: a["browser_download_url"] for a in payload.get("assets", [])}

    def asset_url(name: str) -> str:
        url = assets.get(name, "")
        prefix = f"https://github.com/{repository}/releases/download/{urllib.parse.quote(tag, safe='')}/"
        if not url.startswith(prefix):
            raise UpdateError(f"Release is missing a valid {name} attachment.")
        _check_url(url)
        return url

    raw = fetch_small(asset_url("update.json"), 65536)
    signature = fetch_small(asset_url("update.sig"), 64)
    manifest = Manifest.verify(raw, signature, public_key)
    if manifest.version != target:
        raise UpdateError("Release tag and signed version do not match.")
    return Release(manifest, raw, signature, asset_url(manifest.asset), str(payload.get("body") or "")[:20000])


def download(release: Release, staging: Path, progress: Callable[[int, int], None], cancelled: Callable[[], bool]) -> Path:
    staging.mkdir(parents=True, exist_ok=True)
    manifest = release.manifest
    if shutil.disk_usage(staging).free < manifest.size + manifest.expanded_size + SPACE_RESERVE:
        raise UpdateError("Not enough free disk space for this update.")
    package = staging / "package.zip"
    partial = staging / "package.part"
    try:
        received = 0
        with _open(release.url) as response, partial.open("wb") as handle:
            while True:
                if cancelled():
                    raise Cancelled("Update cancelled.")
                block = response.read(CHUNK)
                if not block:
                    break
                received += len(block)
                if received > manifest.size:
                    raise UpdateError("Downloaded ZIP exceeds its signed size.")
                handle.write(block)
                progress(received, manifest.size)
        manifest.verify_archive(partial, cancelled)
        if cancelled():
            raise Cancelled("Update cancelled.")
        os.replace(partial, package)
        (staging / "update.json").write_bytes(release.raw)
        (staging / "update.sig").write_bytes(release.signature)
        return package
    finally:
        partial.unlink(missing_ok=True)


def archive_members(archive: zipfile.ZipFile, expanded_size: int) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if len(members) > MAX_FILES or sum(m.file_size for m in members) != expanded_size:
        raise UpdateError("ZIP contents do not match the signed expanded size.")
    seen = set()
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}
    for member in members:
        name = member.orig_filename
        if name != member.filename:
            raise UpdateError("ZIP contains a normalized or truncated path.")
        path = PurePosixPath(name)
        parts = name.rstrip("/").split("/")
        if not name or path.is_absolute() or "\\" in name or any(
            not p or p in {".", ".."} or p.endswith((".", " "))
            or any(ord(c) < 32 or c in '<>:"|?*' for c in p)
            or p.split(".")[0].upper() in reserved for p in parts
        ):
            raise UpdateError("ZIP contains an unsafe Windows path.")
        mode = member.external_attr >> 16
        if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR) or member.flag_bits & 1:
            raise UpdateError("ZIP links, special files and encryption are not supported.")
        folded = "/".join(parts).casefold()
        if folded in seen:
            raise UpdateError("ZIP contains duplicate paths.")
        seen.add(folded)
    if EXECUTABLE.casefold() not in seen or not any(p.startswith("_internal/") for p in seen):
        raise UpdateError("ZIP does not contain the complete application and dependencies.")
    return members


def extract_archive(package: Path, destination: Path, manifest: Manifest) -> None:
    # destination is newly created: no pre-existing symlinks/reparse points.
    destination.mkdir(parents=False, exist_ok=False)
    try:
        with zipfile.ZipFile(package) as archive:
            members = archive_members(archive, manifest.expanded_size)
            for member in members:
                target = destination.joinpath(*PurePosixPath(member.filename).parts)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output, CHUNK)
    except Exception:
        # All paths were validated and this function owns this new directory.
        shutil.rmtree(destination)
        raise


def check_release_direct(repository: str, public_key: str, current: str) -> Release | None:
    """Public-release redirect fallback when GitHub's shared API quota is exhausted."""
    with _open(f"https://github.com/{repository}/releases/latest") as response:
        final = urllib.parse.urlparse(response.geturl())
        prefix = f"/{repository}/releases/tag/"
        if final.hostname != "github.com" or not final.path.startswith(prefix):
            raise UpdateError("No public stable release is available yet.")
        tag = urllib.parse.unquote(final.path[len(prefix):])
    target = tag.removeprefix("v")
    if version(target) <= version(current):
        return None
    base = f"https://github.com/{repository}/releases/download/{urllib.parse.quote(tag, safe='')}/"
    try:
        raw = fetch_small(base + "update.json", 65536)
        signature = fetch_small(base + "update.sig", 64)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("The latest release has no signed update package yet.") from exc
        raise
    manifest = Manifest.verify(raw, signature, public_key)
    if manifest.version != target:
        raise UpdateError("Release tag and signed version do not match.")
    return Release(manifest, raw, signature, base + manifest.asset,
                   f"Release notes: https://github.com/{repository}/releases/tag/{tag}")
