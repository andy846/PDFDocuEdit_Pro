"""Fixed, unprivileged Windows launcher. Never replaces its own runtime."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

from updates.protocol import UpdateError, atomic_json, read_json
from updates.runtime import (
    RESTART_EXIT_CODE,
    ROOT_ENV,
    TOKEN_ENV,
    FileLock,
    Installation,
    queue_launch,
)
from updates.trust import PUBLIC_KEY_HEX

STARTUP_TIMEOUT = 120


def notify(message: str) -> None:
    logging.error(message)
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "PDFDocuEdit Pro Update", 0x10)
    else:
        print(message, file=sys.stderr)


def stop_child(child) -> None:
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=10)


def supervise(installation: Installation, arguments: list[str], *, spawn=subprocess.Popen, timeout=STARTUP_TIMEOUT) -> int:
    """The launcher stays alive while the editor runs; only it switches versions."""
    root = installation.root
    while True:
        state = installation.state()
        trial = state["phase"] == "trial"
        token = state["token"] if trial else uuid.uuid4().hex
        environment = os.environ.copy()
        environment.update({ROOT_ENV: str(root), TOKEN_ENV: token, "PYINSTALLER_RESET_ENVIRONMENT": "1"})
        # A frozen child must initialize its own bundled Python and DLL paths.
        atomic_json(root / "launch.json", {"token": token, "version": state["current"]})
        child = None
        try:
            child = spawn([str(installation.executable(state["current"])), *arguments], cwd=root, env=environment)
            deadline = time.monotonic() + timeout
            confirmed = False
            while child.poll() is None:
                ready = root / f"ready-{token}.json"
                if not confirmed and ready.exists() and read_json(ready).get("token") == token:
                    if trial:
                        installation.commit(token)
                        try:
                            installation.cleanup()
                        except OSError:
                            logging.exception("Cleanup postponed")
                    atomic_json(root / f"accepted-{token}.json", {"token": token})
                    confirmed = True
                    logging.info("Version %s started successfully", state["current"])
                if trial and not confirmed and time.monotonic() >= deadline:
                    raise UpdateError("The application did not become ready within 120 seconds.")
                time.sleep(0.1)
            result = child.returncode
            if not confirmed:
                raise UpdateError("The application exited before startup completed.")
        except Exception as exc:
            if child is not None:
                stop_child(child)
            # Never restore files while an orphaned editor still holds its lock.
            with FileLock(root / "app.lock"):
                recovered = installation.recover()
            notify(f"Startup failed: {exc}" + ("\nThe previous version and settings were restored." if recovered else ""))
            if recovered:
                arguments = []
                continue
            return 1
        finally:
            for prefix in ("ready", "accepted"):
                (root / f"{prefix}-{token}.json").unlink(missing_ok=True)
        restart_path = root / "restart.json"
        requested = restart_path.exists() and read_json(restart_path).get("token") == token
        restart_path.unlink(missing_ok=True)
        if result != RESTART_EXIT_CODE or not requested:
            return result
        try:
            with FileLock(root / "app.lock"):
                target = installation.prepare(PUBLIC_KEY_HEX)
                installation.begin_trial(target)
        except Exception as exc:
            logging.exception("Update preparation failed")
            notify(f"Update could not be installed: {exc}\nThe current version will reopen.")
        arguments = []


def main() -> int:
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    try:
        installation = Installation(root)
        handler = RotatingFileHandler(root / "logs" / "updater.log", maxBytes=1024 * 1024, backupCount=2, encoding="utf-8")
        logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")
        launcher_lock = FileLock(root / "launcher.lock")
        paths = [str(Path(arg).resolve()) for arg in sys.argv[1:] if Path(arg).is_file()]
        if not launcher_lock.acquire():
            queue_launch(root, paths)
            return 0
        try:
            with FileLock(root / "app.lock"):
                if installation.recover():
                    notify("An interrupted update was restored to the previous version.")
            return supervise(installation, paths)
        finally:
            launcher_lock.release()
    except Exception as exc:
        notify(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
