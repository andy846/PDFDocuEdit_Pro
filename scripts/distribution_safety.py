"""The one PEM exception is the installed, public certifi CA certificate bundle."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path


def is_public_ca(path: Path, relative: Path) -> bool:
    if relative.as_posix() in {"Contents/Resources/certifi/cacert.pem", "Contents/Frameworks/certifi/cacert.pem"}:
        relative = Path("certifi/cacert.pem")
    if len(relative.parts) == 5 and relative.parts[0] == "versions" and re.fullmatch(r"\d+\.\d+\.\d+", relative.parts[1]):
        relative = Path(*relative.parts[2:])
    if relative.as_posix() not in {"_internal/certifi/cacert.pem", "certifi/cacert.pem"}:
        return False
    try:
        import certifi
        from cryptography import x509
        value = path.read_bytes()
        if b"PRIVATE KEY" in value or not x509.load_pem_x509_certificates(value):
            return False
        return hashlib.sha256(value).digest() == hashlib.sha256(Path(certifi.where()).read_bytes()).digest()
    except (ImportError, OSError, ValueError):
        return False


def assert_public_distribution(root: Path, *, allow_bundle_links=False):
    for path in root.rglob("*"):
        if path.is_symlink() or path.is_junction():
            if not allow_bundle_links or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("Distribution must not contain external links.")
            continue
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(p.casefold() in {"secret", ".update-keys", ".git"} or p.casefold().startswith((".env", ".venv")) for p in relative.parts):
            raise ValueError(f"Private/local file found in distribution: {relative}")
        if path.name.casefold() in {"config.json", "vc_config.json", "settings.json"} or path.suffix.casefold() in {".key", ".log"}:
            raise ValueError(f"Private/local file found in distribution: {relative}")
        if path.suffix.casefold() == ".pem" and not is_public_ca(path, relative):
            raise ValueError(f"Private/local file found in distribution: {relative}")
