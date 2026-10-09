"""Public client configuration; frozen auth builds cannot opt out via environment."""
from __future__ import annotations

import importlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class AuthConfig:
    project_ref: str
    url: str
    publishable_key: str

    @classmethod
    def from_dict(cls, value: dict) -> AuthConfig:
        if not isinstance(value, dict):
            raise ValueError("Invalid public authentication configuration.")
        ref, url, key = (value.get(k, "") for k in ("project_ref", "url", "publishable_key"))
        if (not isinstance(ref, str) or not ref.isalnum() or not isinstance(url, str) or
                urlparse(url).scheme != "https" or urlparse(url).netloc != f"{ref}.supabase.co" or
                url.rstrip("/") != f"https://{ref}.supabase.co" or
                not isinstance(key, str) or not key.startswith("sb_publishable_")):
            raise ValueError("Invalid public authentication configuration.")
        return cls(ref, url.rstrip("/"), key)


def configuration() -> AuthConfig | None:
    if getattr(sys, "frozen", False):
        try:
            build = importlib.import_module("pdfdocuedit_auth_build")
        except ModuleNotFoundError as error:
            if error.name != "pdfdocuedit_auth_build":
                raise
            return None
        # Presence of this compiled module always requires authentication.
        return AuthConfig.from_dict(build.PROJECT)
    if os.environ.get("PDFDOCUEDIT_ENABLE_AUTH") != "1":
        return None
    if sys.platform not in {"win32", "darwin"}:
        raise ValueError("Private authentication builds require Windows or macOS.")
    path = Path(__file__).resolve().parents[1] / "build_assets" / "auth" / "PROJECT.json"
    return AuthConfig.from_dict(json.loads(path.read_text(encoding="utf-8")))
