"""Native frozen private admission/handshake test, without real credentials."""
from __future__ import annotations

import argparse
import json
import os
import signal
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


def run_shell(shell, output):
    """Exercise frozen parent/child isolation, duplicate launch and direct reroute."""
    require_arm64()
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise RuntimeError("Managed shell smoke requires a disposable hosted CI account.")
    shell, output = Path(shell).resolve(), Path(output).resolve()
    settings = json.loads((shell / "Contents/Resources/bootstrap.json").read_text())
    target = UpdateTarget(**settings["target"])
    if target.channel != "private" or ApprovalStore(target.auth_project).load() is not None:
        raise RuntimeError("Managed shell smoke requires a clean private CI account.")
    root = Path.home() / "Library/Application Support/PDFDocuEditPro/managed" / f"private-{target.auth_project}-arm64"
    if root.exists():
        raise RuntimeError("Refusing to touch an existing managed installation.")
    output.mkdir(parents=True, exist_ok=True)
    environment = {k: v for k, v in os.environ.items() if not k.startswith(("DYLD_", "PYTHON", "GS_"))}
    for name in (ROOT_ENV, TOKEN_ENV):
        environment.pop(name, None)
    environment.update(PATH="/usr/bin:/bin:/usr/sbin:/sbin", QT_QPA_PLATFORM="offscreen",
                       PYINSTALLER_RESET_ENVIRONMENT="1")
    executable = shell / "Contents/MacOS/PDFDocuEdit Pro"
    child_pid = None
    with (output / "shell-startup.log").open("w") as log:
        process = subprocess.Popen([str(executable)], cwd=output, env=environment,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 120
            while not list(root.glob("accepted-*.json")):
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Frozen managed shell did not acknowledge its private child.")
                time.sleep(0.1)
            versioned = root / "versions" / settings["version"] / target.executable

            def children():
                result = subprocess.run(["/usr/bin/pgrep", "-P", str(process.pid)], capture_output=True, text=True, timeout=5)
                matches = []
                for value in result.stdout.split():
                    pid = int(value)
                    command = subprocess.check_output(["/bin/ps", "-p", str(pid), "-o", "command="], text=True, timeout=5)
                    if str(versioned) in command:
                        matches.append(pid)
                return matches

            found = children()
            if len(found) != 1:
                raise RuntimeError("Managed shell did not retain exactly one owned editor child.")
            child_pid = found[0]
            subprocess.run([str(executable)], cwd=output, env=environment, stdout=log,
                           stderr=subprocess.STDOUT, timeout=30, check=True)
            subprocess.run([str(versioned)], cwd=output, env=environment, stdout=log,
                           stderr=subprocess.STDOUT, timeout=30, check=True)
            deadline = time.monotonic() + 10
            while list((root / "requests").glob("*.json")) and time.monotonic() < deadline:
                time.sleep(0.1)
            if children() != [child_pid] or list((root / "requests").glob("*.json")):
                raise RuntimeError("Duplicate/direct launch did not route to the existing private login shell.")
            atomic_json(output / "shell-results.json", {"frozen_parent_child": True,
                        "duplicate_launch_routed": True, "direct_version_launch_routed": True})
        finally:
            # Only the observed child of this owned shell is signalled. Leave
            # failed evidence for CI; never delete an operator's installation.
            if child_pid is not None:
                try:
                    os.kill(child_pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shell", type=Path)
    args = parser.parse_args()
    run_shell(args.shell, args.output) if args.shell else run(args.app, args.output)
