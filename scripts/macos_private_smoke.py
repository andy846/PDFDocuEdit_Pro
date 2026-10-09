"""Native frozen private admission/handshake test, without real credentials."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

from auth.store import ApprovalStore
from scripts.prepare_macos import require_arm64
from updates.macos import installation_for, validate_app
from updates.protocol import atomic_json
from updates.runtime import ROOT_ENV, TOKEN_ENV
from updates.target import UpdateTarget


def run(app, output):
    require_arm64()
    app, output = Path(app).resolve(), Path(output).resolve()
    target = UpdateTarget(**json.loads((app / "Contents/Resources/update-target.json").read_text()))
    if target.channel != "private":
        raise RuntimeError("Private smoke requires an account-gated application.")
    # Never run this test against an operator's saved approval or clear it.
    if ApprovalStore(target.auth_project).load() is not None:
        raise RuntimeError("Use a clean Mac CI account; a real saved approval exists.")
    from core.resources import APP_VERSION
    validate_app(app.parent, APP_VERSION, target)
    output.mkdir(parents=True, exist_ok=True)
    installation = installation_for(app, APP_VERSION, target, base=output / "managed")
    token = uuid.uuid4().hex
    atomic_json(installation.root / "launch.json", {"token": token, "version": APP_VERSION})
    environment = {k: v for k, v in os.environ.items() if not k.startswith(("DYLD_", "PYTHON", "GS_"))}
    environment.update(PATH="/usr/bin:/bin:/usr/sbin:/sbin", QT_QPA_PLATFORM="offscreen",
                       PYINSTALLER_RESET_ENVIRONMENT="1")
    environment[ROOT_ENV], environment[TOKEN_ENV] = str(installation.root), token
    executable = installation.executable(APP_VERSION)
    with (output / "login-startup.log").open("w") as log:
        process = subprocess.Popen([str(executable)], cwd=output, env=environment,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 90
            ready = installation.root / f"ready-{token}.json"
            while not ready.exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Frozen private login did not complete its startup handshake.")
                time.sleep(0.1)
            if json.loads(ready.read_text()).get("token") != token:
                raise RuntimeError("Private handshake token differs.")
            atomic_json(installation.root / f"accepted-{token}.json", {"token": token})
            time.sleep(1)
            if process.poll() is not None:
                raise RuntimeError("Frozen private login exited unexpectedly.")
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
    # Workers and the public QA entry must fail before GUI/PDF imports.
    for flag in ("--composition-worker", "--print-worker", "--pdf-operations-worker", "--composition-smoke", "--macos-smoke"):
        result = subprocess.run([str(executable), flag, str(output / "not-created")],
                                cwd=output, env=environment, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 or "approved account" not in (result.stdout + result.stderr):
            raise RuntimeError(f"Private admission guard failed: {flag}")
    if (output / "not-created").exists():
        raise RuntimeError("A denied entry created output.")
    atomic_json(output / "results.json", {"login_shell_started": True, "managed_handshake": True,
                "unauthenticated_entries_blocked": True, "real_account_tested": False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.app, args.output)
