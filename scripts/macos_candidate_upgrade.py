"""Operator-only signed candidate upgrade before the GitHub draft is public.

Uses the unchanged production transaction/supervisor. Close the installed
application first; keep this terminal open until the upgraded app is closed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from launcher import supervise
from scripts.prepare_macos import require_arm64
from updates.macos import validate_app
from updates.protocol import Manifest, UpdateError, atomic_json, version
from updates.runtime import FileLock, Installation
from updates.target import UpdateTarget
from updates.trust import PUBLIC_KEY_HEX


def verify_candidate(app, folder):
    settings = json.loads((app / "Contents/Resources/bootstrap.json").read_text(encoding="utf-8"))
    target = UpdateTarget(**settings["target"])
    if target.platform != "macos-arm64" or target.channel != "private":
        raise UpdateError("Select the installed account-enabled Mac Managed application.")
    raw = (folder / (target.metadata + ".json")).read_bytes()
    if len(raw) > 65536:
        raise UpdateError("Candidate metadata exceeds limits.")
    signature = (folder / (target.metadata + ".sig")).read_bytes()
    manifest = Manifest.verify(raw, signature, PUBLIC_KEY_HEX, target=target, application_target=target)
    package = folder / manifest.asset
    manifest.verify_archive(package)
    return target, manifest, package, raw, signature


def run(app, folder, report):
    require_arm64()
    app, folder, report = Path(app).resolve(), Path(folder).resolve(), Path(report).resolve()
    target, manifest, package, raw, signature = verify_candidate(app, folder)
    root = Path.home() / "Library/Application Support/PDFDocuEditPro/managed" / f"private-{target.auth_project}-arm64"
    if report.is_relative_to(root.resolve()):
        raise UpdateError("Save the test report outside the managed installation.")
    if not (root / "state.json").is_file():
        raise UpdateError("Open the installed Managed application once before testing an upgrade.")
    # This is an operator's installation: refuse active applications or pending
    # work rather than replacing, terminating or deleting it.
    with FileLock(root / "launcher.lock"):
        with FileLock(root / "app.lock"):
            installation = Installation(root, target=target, validator=validate_app)
            state = installation.state()
            before = state["current"]
            if state["phase"] != "stable" or version(manifest.version) <= version(before):
                raise UpdateError("A stable older installation is required; open the existing app to recover pending work.")
            registered = json.loads((root / "installation.json").read_text(encoding="utf-8"))
            if Path(registered["launcher"]).resolve() != (app / "Contents/MacOS/PDFDocuEdit Pro").resolve():
                raise UpdateError("Selected application is not this installation's registered launcher.")
            stage = root / "staging"
            if any(stage.iterdir()):
                raise UpdateError("An existing staged update was found; it has been left untouched.")
            partial = stage / "package.part"
            try:
                shutil.copyfile(package, partial)
                manifest.verify_archive(partial)
                os.replace(partial, stage / "package.zip")
                (stage / "update.json").write_bytes(raw)
                (stage / "update.sig").write_bytes(signature)
                prepared = installation.prepare(PUBLIC_KEY_HEX)
                installation.begin_trial(prepared)
            finally:
                partial.unlink(missing_ok=True)
        print(f"Starting signed candidate {manifest.version}. Keep this terminal open; close the app after testing.", flush=True)
        result = supervise(installation, [], notify_callback=lambda message: print(message, flush=True))
        state = installation.state()
        passed = result == 0 and state["phase"] == "stable" and state["current"] == manifest.version
        atomic_json(report, {"mac_cross_version_update": passed, "before": before, "after": state["current"],
                             "package_sha256": manifest.sha256, "real_account_login_confirmed": False,
                             "uses_shared_transaction_and_supervisor": True})
        if not passed:
            raise UpdateError("Candidate did not complete successfully. Inspect the saved report; the normal rollback policy was retained.")
        return state["current"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=Path("/Applications/PDFDocuEdit Pro.app"))
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.app, args.folder, args.report)
    except (UpdateError, RuntimeError, OSError, ValueError, KeyError) as exc:
        print(f"Candidate upgrade stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
