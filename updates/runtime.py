"""Recoverable version transactions and launcher/app coordination."""

from __future__ import annotations

import os
import shutil
import sys
import uuid
from pathlib import Path

from .protocol import (
    EXECUTABLE,
    SPACE_RESERVE,
    Manifest,
    UpdateError,
    atomic_json,
    extract_archive,
    read_json,
    version,
)

ROOT_ENV = "PDFDOCUEDIT_UPDATE_ROOT"
TOKEN_ENV = "PDFDOCUEDIT_LAUNCH_TOKEN"
RESTART_EXIT_CODE = 75


def managed_root() -> Path | None:
    value = os.environ.get(ROOT_ENV)
    return Path(value).resolve() if value else None


class FileLock:
    """OS-owned lock: process death releases it without stale-PID guessing."""

    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self.handle.close()
            self.handle = None
            return False

    def release(self) -> None:
        if self.handle is not None:
            self.handle.close()
            self.handle = None

    def __enter__(self):
        if not self.acquire():
            raise UpdateError("Another application instance is still running. Close it and try again.")
        return self

    def __exit__(self, *_args):
        self.release()


def queue_launch(root: Path, paths: list[str]) -> None:
    atomic_json(root / "requests" / f"{uuid.uuid4().hex}.json", {"paths": paths})


class Installation:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.state_path = self.root / "state.json"
        for name in ("versions", "staging", "data", "backups", "logs", "requests"):
            path = self.root / name
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise UpdateError(f"Managed directory cannot be a link: {name}")
            path.mkdir(parents=True, exist_ok=True)

    def state(self) -> dict:
        state = read_json(self.state_path)
        version(state["current"])
        if state.get("previous"):
            version(state["previous"])
        if state.get("phase") not in {"stable", "trial", "rollback"}:
            raise UpdateError("Unknown update state. Restore the deployment backup.")
        return state

    def executable(self, value: str) -> Path:
        version(value)
        folder = self.root / "versions" / value
        if folder.resolve().parent != (self.root / "versions").resolve():
            raise UpdateError("Version directory points outside the installation.")
        executable = folder / EXECUTABLE
        if not executable.is_file():
            raise UpdateError(f"Application executable is missing for version {value}.")
        return executable

    def prepare(self, public_key: str) -> str:
        stage = self.root / "staging"
        manifest = Manifest.verify((stage / "update.json").read_bytes(), (stage / "update.sig").read_bytes(), public_key)
        state = self.state()
        if state["phase"] != "stable" or version(manifest.version) <= version(state["current"]):
            raise UpdateError("Update is not newer than the active stable version.")
        manifest.verify_archive(stage / "package.zip")
        data_size = sum(p.stat().st_size for p in (self.root / "data").rglob("*") if p.is_file())
        if shutil.disk_usage(self.root).free < manifest.expanded_size + data_size * 2 + SPACE_RESERVE:
            raise UpdateError("Not enough free space to extract the update and back up settings.")
        target = self.root / "versions" / manifest.version
        if target.exists():
            raise UpdateError("This version directory already exists. Preserve or remove it manually before retrying.")
        temporary = self.root / "versions" / f".staging-{uuid.uuid4().hex}"
        extract_archive(stage / "package.zip", temporary, manifest)
        (temporary / ".managed-update").write_text(manifest.version, encoding="utf-8")
        temporary.rename(target)
        return manifest.version

    def begin_trial(self, target: str) -> dict:
        state = self.state()
        self.executable(target)
        if state["phase"] != "stable" or version(target) <= version(state["current"]):
            raise UpdateError("Invalid update transition.")
        token = uuid.uuid4().hex
        backup = self.root / "backups" / token
        # No application is running during snapshot/cutover. Only managed data
        # is copied; user PDF documents are never moved or restored.
        for path in (self.root / "data").rglob("*"):
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise UpdateError("Settings backup contains a link. Resolve it before updating.")
        shutil.copytree(self.root / "data", backup)
        trial = {"current": target, "previous": state["current"], "phase": "trial", "token": token, "backup": token}
        atomic_json(self.state_path, trial)
        return trial

    def commit(self, token: str) -> None:
        state = self.state()
        if state["phase"] != "trial" or state.get("token") != token:
            raise UpdateError("Stale startup confirmation.")
        atomic_json(self.state_path, {"current": state["current"], "previous": state["previous"], "phase": "stable"})

    def recover(self) -> bool:
        state = self.state()
        if state["phase"] == "stable":
            return False
        backup_name = state.get("backup", "")
        if len(backup_name) != 32 or any(c not in "0123456789abcdef" for c in backup_name):
            raise UpdateError("Invalid settings backup reference.")
        backup = self.root / "backups" / backup_name
        if not backup.is_dir():
            raise UpdateError("Settings backup is missing; automatic rollback stopped.")
        self.executable(state["previous"])
        state["phase"] = "rollback"
        atomic_json(self.state_path, state)
        restored = self.root / "backups" / f"restore-{uuid.uuid4().hex}"
        shutil.copytree(backup, restored)
        data = self.root / "data"
        if data.exists():
            data.rename(self.root / "backups" / f"failed-data-{uuid.uuid4().hex}")
        restored.rename(data)
        failed_version = self.root / "versions" / state["current"]
        if failed_version.exists() and (failed_version / ".managed-update").is_file():
            failed_version.rename(self.root / "backups" / f"failed-version-{uuid.uuid4().hex}")
        atomic_json(self.state_path, {"current": state["previous"], "previous": None, "phase": "stable"})
        return True

    def cleanup(self) -> None:
        state = self.state()
        keep = {state["current"], state.get("previous")}
        for path in (self.root / "versions").iterdir():
            if path.name in keep or not (path / ".managed-update").is_file():
                continue
            if path.resolve().parent != (self.root / "versions").resolve():
                continue
            version(path.name)
            shutil.rmtree(path)
        for name in ("package.zip", "package.part", "update.json", "update.sig"):
            (self.root / "staging" / name).unlink(missing_ok=True)


def request_restart(root: Path) -> None:
    atomic_json(root / "restart.json", {"token": os.environ.get(TOKEN_ENV, "")})
