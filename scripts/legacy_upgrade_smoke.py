"""Two real frozen upgrades through the unchanged v3.0.3 Windows launcher."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from scripts.build_managed_installer import extract_deployment
from updates.protocol import Manifest, UpdateError, atomic_json, digest_file, read_json, version
from updates.target import LEGACY_WINDOWS_LAUNCHERS
from updates.trust import PUBLIC_KEY_HEX


def child_of(parent, expected):
    query = (f'Get-CimInstance Win32_Process -Filter "ParentProcessId = {parent}" | '
             "Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", query],
                            capture_output=True, text=True, timeout=15, check=True)
    values = json.loads(result.stdout) if result.stdout.strip() else []
    values = values if isinstance(values, list) else [values]
    return next((row["ProcessId"] for row in values if row.get("ExecutablePath") and
                 Path(row["ExecutablePath"]).resolve() == expected.resolve()), None)


def stop_owned(pid, code):
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    api.OpenProcess.restype = ctypes.c_void_p
    api.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    api.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = api.OpenProcess(1, False, pid)
    if not handle:
        raise OSError("Cannot stop the observed isolated QA child.")
    try:
        if not api.TerminateProcess(handle, code):
            raise OSError("Cannot stop the observed isolated QA child.")
    finally:
        api.CloseHandle(handle)


def run(baseline, releases, output):
    if sys.platform != "win32" or len(releases) != 2:
        raise UpdateError("This gate requires Windows and exactly two newer signed frozen versions.")
    output = Path(output).resolve()
    if output.exists():
        raise UpdateError("Use a fresh QA folder; no existing application/user files are touched.")
    output.mkdir(parents=True)
    root = extract_deployment(Path(baseline), output, "3.0.3")
    launcher = root / "Launcher.exe"
    original_hash = digest_file(launcher)
    if original_hash not in LEGACY_WINDOWS_LAUNCHERS:
        raise UpdateError("Baseline is not the allowlisted original frozen launcher.")
    (root / "data").mkdir(exist_ok=True)
    (root / "data/.migration-complete").touch()
    sentinel = root / "data/project-paths.json"
    sentinel.write_text('{"project":"C:/QA/測試/template.pdcx","theme":"dark"}', encoding="utf-8")
    saved = sentinel.read_bytes()
    stage = root / "staging"
    stage.mkdir(exist_ok=True)
    manifests = []
    previous = "3.0.3"
    for folder in map(Path, releases):
        manifest = Manifest.verify((folder / "update.json").read_bytes(), (folder / "update.sig").read_bytes(), PUBLIC_KEY_HEX)
        manifest.verify_archive(folder / manifest.asset)
        if (version(manifest.version) <= version(previous) or manifest.application_target is None
                or manifest.application_target.channel != "private"):
            raise UpdateError("Each QA update must be a newer account-enabled application.")
        manifests.append((folder, manifest))
        previous = manifest.version
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    for name in ("PDFDOCUEDIT_UPDATE_ROOT", "PDFDOCUEDIT_LAUNCH_TOKEN"):
        environment.pop(name, None)
    observed = []
    owned_child = None
    process = subprocess.Popen([str(launcher)], cwd=root, env=environment)
    try:
        for index, expected_version in enumerate(["3.0.3", *[m.version for _, m in manifests]]):
            deadline = time.monotonic() + 120
            while True:
                if process.poll() is not None:
                    raise UpdateError("The original frozen launcher exited during upgrade acceptance.")
                path = root / "launch.json"
                launch = read_json(path) if path.exists() else {}
                token = launch.get("token", "")
                accepted = root / f"accepted-{token}.json"
                if launch.get("version") == expected_version and accepted.exists():
                    if read_json(accepted).get("token") == token:
                        break
                if time.monotonic() > deadline:
                    raise UpdateError(f"Frozen {expected_version} did not become ready.")
                time.sleep(.1)
            owned_child = child_of(process.pid, root / "versions" / expected_version / "PDFDocuEdit Pro.exe")
            if not owned_child:
                raise UpdateError("Could not identify the launcher's exact isolated child.")
            observed.append(expected_version)
            if index < 2:
                folder, manifest = manifests[index]
                for name in ("update.json", "update.sig"):
                    shutil.copyfile(folder / name, stage / name)
                shutil.copyfile(folder / manifest.asset, stage / "package.zip")
                atomic_json(root / "restart.json", {"token": token})
                stop_owned(owned_child, 75)
                owned_child = None
            else:
                stop_owned(owned_child, 0)
                owned_child = None
        if process.wait(20) != 0 or sentinel.read_bytes() != saved or digest_file(launcher) != original_hash:
            raise UpdateError("Final exit, preserved settings or unchanged launcher gate failed.")
        report = {"passed": True, "windows_two_upgrades": True, "observed_versions": observed,
                  "original_frozen_launcher": True, "launcher_sha256": original_hash,
                  "settings_preserved": True, "restart_method": "owned empty QA child exit code"}
        atomic_json(output / "result.json", report)
        return report
    finally:
        if owned_child:
            stop_owned(owned_child, 1)
        if process.poll() is None:
            process.terminate()
            process.wait(15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--updates", type=Path, nargs=2, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.baseline, args.updates, args.output), indent=2))


if __name__ == "__main__":
    main()
