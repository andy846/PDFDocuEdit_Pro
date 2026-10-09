"""Windows Credential Manager only; never fall back to files or other keyrings."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict

from .model import Approval


class StorageError(Exception):
    pass


class ApprovalStore:
    def __init__(self, project_ref: str, *, backend=None):
        self.project_ref = project_ref
        self.service = f"PDFDocuEditPro.PrivateAccess.{project_ref}"
        self.username = "approval-v1"
        if backend is None:
            if sys.platform != "win32":
                raise StorageError("Windows Credential Manager is required.")
            from keyring.backends.Windows import WinVaultKeyring
            backend = WinVaultKeyring()
        self.backend = backend

    def load(self) -> Approval | None:
        try:
            raw = self.backend.get_password(self.service, self.username)
        except Exception:
            raise StorageError("Cannot read Windows Credential Manager.") from None
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
            raise StorageError("Session exceeds Windows Credential Manager capacity.")
        try:
            self.backend.set_password(self.service, self.username, raw)
        except Exception:
            raise StorageError("Cannot save approval in Windows Credential Manager.") from None

    def clear(self) -> None:
        try:
            if self.backend.get_password(self.service, self.username) is not None:
                self.backend.delete_password(self.service, self.username)
        except Exception:
            raise StorageError("Cannot clear Windows Credential Manager. Access remains locked.") from None
