"""Explicit OS credential stores; never fall back to plain files or keyrings."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from .model import Approval


class StorageError(Exception):
    pass


class ApprovalStore:
    def __init__(self, project_ref: str, *, backend=None, blocked_path=None):
        self.project_ref = project_ref
        self.service = f"PDFDocuEditPro.PrivateAccess.{project_ref}"
        self.username = "approval-v1"
        self.storage_name = "the system credential store"
        # This marker contains no account data or credentials. It prevents an
        # old Credential Manager entry being reused if deletion is refused.
        self.blocked_path = Path(blocked_path) if blocked_path is not None else None
        if backend is None:
            if sys.platform == "win32":
                from keyring.backends.Windows import WinVaultKeyring
                backend = WinVaultKeyring()
                self.storage_name = "Windows Credential Manager"
                local = os.environ.get("LOCALAPPDATA")
                if not local:
                    raise StorageError("Windows local application storage is unavailable.")
                base = Path(local)
            elif sys.platform == "darwin":
                from keyring.backends.macOS import Keyring
                backend = Keyring()
                self.storage_name = "macOS Keychain"
                base = Path.home() / "Library/Application Support"
            else:
                raise StorageError("A supported OS credential store is required.")
            self.blocked_path = base / "PDFDocuEditPro/private-access" / project_ref / "require-signin"
        self.backend = backend

    def load(self) -> Approval | None:
        try:
            if self.blocked_path is not None and self.blocked_path.exists():
                return None
            raw = self.backend.get_password(self.service, self.username)
        except Exception:
            raise StorageError(f"Cannot read {self.storage_name}.") from None
        if raw is None:
            return None
        try:
            if len(raw.encode("utf-16-le")) > 4096:
                return None
            approval = Approval(**json.loads(raw))
            approval.validate(self.project_ref)
            return approval
        except (TypeError, ValueError, AttributeError):
            return None

    def save(self, approval: Approval) -> None:
        approval.validate(self.project_ref)
        raw = json.dumps(asdict(approval), ensure_ascii=True, separators=(",", ":"))
        if len(raw.encode("utf-16-le")) > 4096:
            raise StorageError("Session exceeds supported credential-store capacity.")
        try:
            self.backend.set_password(self.service, self.username, raw)
            if self.backend.get_password(self.service, self.username) != raw:
                raise StorageError("Credential write verification failed.")
            if self.blocked_path is not None:
                self.blocked_path.unlink(missing_ok=True)
        except Exception:
            raise StorageError(f"Cannot save approval in {self.storage_name}.") from None

    def clear(self) -> None:
        marker_written = False
        if self.blocked_path is not None:
            try:
                self.blocked_path.parent.mkdir(parents=True, exist_ok=True)
                self.blocked_path.write_text("", encoding="utf-8")
                marker_written = True
            except OSError:
                pass
        try:
            if self.backend.get_password(self.service, self.username) is not None:
                self.backend.delete_password(self.service, self.username)
            if self.backend.get_password(self.service, self.username) is not None:
                raise StorageError("Credential deletion verification failed.")
        except Exception:
            raise StorageError(f"Cannot clear {self.storage_name}. " +
                               ("Saved approval is blocked until sign-in." if marker_written else
                                "Access remains locked; contact support before restarting.")) from None
