"""Native account release candidates; contains no update signing key or publish."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from core.resources import APP_VERSION
from scripts.distribution_safety import assert_public_distribution
from scripts.update_release import source_fingerprint
from updates.protocol import UpdateError, atomic_json, digest_file
from updates.target import UpdateTarget

ROOT = Path(__file__).resolve().parents[1]


def candidate_record(output, target, files, checks, *, scope="all"):
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    rows = []
    for file in files:
        if file is not None:
            rows.append({"name": file.name, "size": file.stat().st_size, "sha256": digest_file(file)})
    data = {"schema": 1, "release_scope": scope, "version": APP_VERSION, "source_commit": commit,
            "source_fingerprint": source_fingerprint(), "platform": target.platform,
            "channel": target.channel, "auth_project": target.auth_project,
            "checks": checks, "files": rows}
    atomic_json(output / f"candidate-{target.platform}.json", data)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--updates-only", action="store_true")
    args = parser.parse_args()
    if args.updates_only and sys.platform != "win32":
        raise UpdateError("Update-only candidates require Windows x64.")
    changes = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).splitlines()
    # The Mac native preparer refreshes this tracked runtime manifest, not code.
    allowed = {"build_assets/composition/BUNDLE_INFO.json"} if sys.platform == "darwin" else set()
    if any(row[3:] not in allowed or row[:2].strip() != "M" for row in changes):
        raise UpdateError("Freeze and commit the release source before native builds.")
    os.environ["PDFDOCUEDIT_BUILD_AUTH"] = "1"
    project = json.loads((ROOT / "build_assets/auth/PROJECT.json").read_text(encoding="utf-8"))
    platform = "windows-x64" if sys.platform == "win32" else "macos-arm64"
    target = UpdateTarget(platform, "private", project["project_ref"])
    output = ROOT / "release-candidate"
    output.mkdir(exist_ok=True)
    atomic_json(ROOT / "build_assets/update_build.json", {
        "version": APP_VERSION, "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_fingerprint": source_fingerprint(), "composition_enabled": True,
    })
    if sys.platform == "win32":
        from scripts.build import _clean_portable_tree
        from scripts.build_managed_installer import build_installer, extract_deployment
        from scripts.private_auth_packaged_qa import shell
        from scripts.update_release import build_launcher, create_legacy_auth_bridge, create_packages
        subprocess.run([sys.executable, "-m", "scripts.build", "--composition",
                        "--updates-only" if args.updates_only else "--portable-only"], cwd=ROOT, check=True)
        app = ROOT / "dist/PDFDocuEdit Pro"
        _clean_portable_tree(app)
        assert_public_distribution(app)
        launcher = build_launcher(target=target)
        files = create_packages(app, launcher, output, APP_VERSION, None, target=target, updates_only=args.updates_only)
        files.extend(create_legacy_auth_bridge(output, APP_VERSION, target))
        if not args.updates_only:
            installer = build_installer(files[3], APP_VERSION, account_release=True)
            shutil.copy2(installer, output / installer.name)
            shutil.copy2(installer.with_suffix(".exe.sha256"), output / (installer.name + ".sha256"))
            files.extend([output / installer.name, output / (installer.name + ".sha256")])
        smoke = ROOT / "build/windows-release-smoke"
        if smoke.exists():
            raise UpdateError("Use a fresh native smoke directory.")
        smoke.mkdir()
        if args.updates_only:
            # The frozen smoke needs a managed tree, not a distributable Portable ZIP.
            deployment = smoke / "PDFDocuEditPro"
            shutil.copytree(launcher, deployment)
            application = deployment / "versions" / APP_VERSION
            shutil.copytree(app, application)
            (application / ".managed-update").write_text(APP_VERSION, encoding="utf-8")
            atomic_json(deployment / "state.json", {"current": APP_VERSION, "previous": None, "phase": "stable"})
        else:
            deployment = extract_deployment(files[3], smoke, APP_VERSION)
        from auth.store import ApprovalStore
        if ApprovalStore(target.auth_project).load() is not None:
            raise UpdateError("Login-shell acceptance requires an isolated OS test account, not an existing real approval.")
        checks = {"frozen_login": shell(deployment, {**os.environ, "QT_QPA_PLATFORM": "offscreen"})}
        denied = []
        for flag in ("--composition-worker", "--print-worker", "--pdf-operations-worker"):
            result = subprocess.run([str(app / "PDFDocuEdit Pro.exe"), flag], capture_output=True, timeout=30)
            if result.returncode == 0:
                raise UpdateError("Unauthenticated frozen worker was admitted.")
            denied.append(flag)
        checks.update(worker_admission=denied, native_packaging=True)
        evidence = ROOT / "build/ci-release/result.json"
    elif sys.platform == "darwin":
        from scripts.build_macos_managed import main as managed
        subprocess.run([sys.executable, "-m", "scripts.build", "--composition"], cwd=ROOT, check=True)
        subprocess.run([sys.executable, "-m", "scripts.macos_private_smoke", "--app", "dist/PDFDocuEdit Pro.app",
                        "--output", "build/macos-release-smoke"], cwd=ROOT, check=True)
        managed()
        subprocess.run([sys.executable, "-m", "scripts.macos_private_smoke", "--app", "dist/PDFDocuEdit Pro.app",
                        "--shell", "dist-mac-shell/PDFDocuEdit Pro.app", "--output", "build/macos-release-smoke"],
                       cwd=ROOT, check=True)
        names = [target.asset(APP_VERSION), target.asset(APP_VERSION) + ".sha256",
                 f"candidate-{target.metadata}.json",
                 f"PDFDocuEdit-Pro-v{APP_VERSION}-Managed-macOS-arm64-Private.dmg"]
        names.append(names[-1] + ".sha256")
        files = []
        for name in names:
            shutil.copy2(ROOT / "release" / name, output / name)
            files.append(output / name)
        checks = {"frozen_login": json.loads((ROOT / "build/macos-release-smoke/results.json").read_text()),
                  "managed_shell": json.loads((ROOT / "build/macos-release-smoke/shell-results.json").read_text()),
                  "native_packaging": True, "notarized": False}
        evidence = ROOT / "build/macos-tests/result.json"
    else:
        raise UpdateError("Release candidates require Windows x64 or Apple Silicon macOS.")
    rows = json.loads(evidence.read_text(encoding="utf-8"))
    if not rows or any(row["exit_code"] for row in rows):
        raise UpdateError("Native regression evidence is missing or has failures.")
    checks["regression"] = {"passed": True, "modules": len(rows), "tests": sum(row.get("tests", 0) for row in rows),
                            "evidence_sha256": digest_file(evidence)}
    candidate_record(output, target, files, checks, scope="windows-update" if args.updates_only else "all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
