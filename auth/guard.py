"""Local worker admission check. This is an access gate, not tamper-proof DRM."""
from __future__ import annotations

runtime_access: bool | None = None
recovery_saving = False


def recovery_save_allowed(request):
    return recovery_saving and (request.get("task") in {"save", "overlay_save"} or
                               (request.get("task") == "workflow" and request.get("operation") == "save"))


def worker_allowed() -> bool:
    if runtime_access is True:
        return True
    if runtime_access is False:
        return False
    from .config import configuration
    try:
        config = configuration()
        if config is None:
            return True
        from .store import ApprovalStore
        return ApprovalStore(config.project_ref).load() is not None
    except Exception:
        return False


def require_worker_access() -> None:
    if not worker_allowed():
        raise SystemExit("Private build: sign in with an approved account before running a worker.")
