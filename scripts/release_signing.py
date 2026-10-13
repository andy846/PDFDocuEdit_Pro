"""Shared update signing, independent of native packaging and GUI."""
from __future__ import annotations

import getpass
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from updates.protocol import Manifest, UpdateError
from updates.target import DEFAULT_TARGET, UpdateTarget


def load_signing_key(path: Path, *, password_reader=getpass.getpass):
    value = Path(path).read_bytes()
    try:
        key = serialization.load_pem_private_key(value, password=None)
    except TypeError:
        key = serialization.load_pem_private_key(value, password=password_reader("Signing-key password: ").encode())
    from updates.trust import PUBLIC_KEY_HEX
    if not isinstance(key, Ed25519PrivateKey) or key.public_key().public_bytes_raw().hex() != PUBLIC_KEY_HEX:
        raise UpdateError("Signing key does not match the existing update trust anchor.")
    return key


def write_update_metadata(output, metadata, key=None, *, public_key=None):
    target = (DEFAULT_TARGET if metadata["schema"] == 1 else
              UpdateTarget(metadata["platform"], metadata["channel"], metadata.get("auth_project", "")))
    raw = json.dumps(metadata, sort_keys=True, indent=2).encode("utf-8")
    output = Path(output)
    prefix = "" if key is not None else "candidate-"
    path = output / (prefix + target.metadata + ".json")
    if key is not None:
        from updates.trust import PUBLIC_KEY_HEX
        public_key = public_key or PUBLIC_KEY_HEX
        if key.public_key().public_bytes_raw().hex() != public_key:
            raise UpdateError("Signing key does not match the existing update trust anchor.")
        signature = key.sign(raw)
        Manifest.verify(raw, signature, public_key, target=target)
        path.write_bytes(raw)
        signature_path = output / (target.metadata + ".sig")
        signature_path.write_bytes(signature)
        return path, signature_path
    path.write_bytes(raw)
    return path, None
