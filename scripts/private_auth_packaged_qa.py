"""Isolated frozen login-shell/worker/installer checks without test passwords."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def shell(root, environment):
    from core.resources import APP_VERSION
    from updates.protocol import read_json

    started = time.monotonic()
    launcher = subprocess.Popen([str(root / "Launcher.exe")], cwd=root, env=environment)
    child = None
    accepted = False
    try:
        deadline = started + 60
        while time.monotonic() < deadline:
            if launcher.poll() is not None:
                raise RuntimeError("Frozen launcher exited before login-shell readiness.")
            launch = root / "launch.json"
            if launch.exists():
                token = read_json(launch)["token"]
                if (root / f"accepted-{token}.json").exists():
                    accepted = True
                    break
            time.sleep(.05)
        if not accepted:
            raise TimeoutError("Frozen login shell did not acknowledge readiness.")
        expected = (root / "versions" / APP_VERSION / "PDFDocuEdit Pro.exe").resolve()
        query = f'Get-CimInstance Win32_Process -Filter "ParentProcessId = {launcher.pid}" | Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress'
        found = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", query],
                               capture_output=True, text=True, check=True, timeout=15)
        children = json.loads(found.stdout)
        children = children if isinstance(children, list) else [children]
        child = next(p["ProcessId"] for p in children if p.get("ExecutablePath") and Path(p["ExecutablePath"]).resolve() == expected)
        # Stop only this harness's empty, unauthenticated child with success.
        # No desktop actions, account entry, unsaved work or existing process.
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
        api.OpenProcess.restype = ctypes.c_void_p
        api.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        api.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = api.OpenProcess(1, False, child)
        if not handle:
            raise OSError("Cannot stop the isolated QA child.")
        try:
            if not api.TerminateProcess(handle, 0):
                raise OSError("Cannot stop the isolated QA child.")
        finally:
            api.CloseHandle(handle)
        assert launcher.wait(15) == 0
        assert read_json(root / "state.json")["phase"] == "stable"
        return {"accepted_before_login": True, "seconds": round(time.monotonic() - started, 2),
                "real_frozen_launcher": True, "qa_shutdown": "empty login child stopped by harness"}
    finally:
        if launcher.poll() is None:
            if child:
                handle = api.OpenProcess(1, False, child)
                if handle:
                    api.TerminateProcess(handle, 0)
                    api.CloseHandle(handle)
            launcher.terminate()
            launcher.wait(10)


def associations():
    import winreg
    result = {}
    for path in (r"Software\Classes\PDFDocuEditPro.Managed.Document\shell\open\command",
                 r"Software\RegisteredApplications"):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                result[path] = winreg.QueryValueEx(key, "PDFDocuEdit Pro Managed" if "Registered" in path else "")[0]
        except FileNotFoundError:
            result[path] = None
    return result


def main():
    if sys.platform != "win32":
        raise RuntimeError("Windows packaged acceptance only.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / "build"):
        raise RuntimeError("Use a fresh directory under this worktree's build folder.")
    import winreg

    from auth.config import AuthConfig
    from auth.store import ApprovalStore
    from composition.template.model import Template
    from core.resources import APP_VERSION
    from scripts.build_managed_installer import extract_deployment
    from scripts.distribution_safety import assert_public_distribution
    from updates.protocol import digest_file

    config = AuthConfig.from_dict(json.loads((ROOT / "build_assets/auth/PROJECT.json").read_text(encoding="utf-8")))
    if ApprovalStore(config.project_ref).load() is not None:
        raise RuntimeError("This check requires an unapproved Windows user; it will not erase existing approval.")
    uninstall_key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{78A4BA20-C425-4B80-9360-4F07D06F786D}_is1"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, uninstall_key):
            raise RuntimeError("Existing private test installation found; it will not be replaced.")
    except FileNotFoundError:
        pass
    output.mkdir(parents=True)
    report = {"real_account_login": "pending owner-provisioned accounts", "credentials_used": False}
    package = ROOT / "release" / f"PDFDocuEdit-Pro-v{APP_VERSION}-Private-Auth-Managed-Portable-Windows-x64.zip"
    assert digest_file(package) == package.with_suffix(".zip.sha256").read_text().split()[0]
    portable = extract_deployment(package, output / "portable", APP_VERSION)
    assert_public_distribution(portable)
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PDFDOCUEDIT_ENABLE_AUTH": "0",
                   "HTTPS_PROXY": "http://127.0.0.1:1", "NO_PROXY": ""}
    executable = portable / "versions" / APP_VERSION / "PDFDocuEdit Pro.exe"
    request = output / "unauthorized.request.json"
    request.write_text(json.dumps({"task": "save", "target": str(output / "unauthorized.pdcx"),
                                   "template": Template().to_dict()}), encoding="utf-8")
    denied = []
    for flag in ("--composition-worker", "--pdf-operations-worker", "--print-worker", "--composition-smoke"):
        result = subprocess.run([str(executable), flag, str(request)], env=environment,
                                capture_output=True, timeout=30)
        assert result.returncode != 0, flag
        assert not (output / "unauthorized.pdcx").exists(), flag
        denied.append(flag)
    report["denied_worker_flags"] = denied
    report["portable"] = shell(portable, environment)
    before = associations()
    setup = ROOT / "release" / f"PDFDocuEdit-Pro-v{APP_VERSION}-Private-Auth-Setup-Windows-x64.exe"
    installed = output / "installed"
    assert installed.is_relative_to(output)
    result = subprocess.run([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOICONS",
                             "/NOCLOSEAPPLICATIONS", "/NORESTARTAPPLICATIONS", "/TASKS=",
                             f"/DIR={installed}", f"/LOG={output / 'setup.log'}"], timeout=180)
    assert result.returncode == 0
    try:
        assert associations() == before
        report["setup"] = shell(installed, environment)
    finally:
        uninstall = (installed / "unins000.exe").resolve()
        assert uninstall.is_relative_to(output)
        result = subprocess.run([str(uninstall), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=90)
        assert result.returncode == 0
    assert associations() == before
    report.update({"public_associations_preserved": True, "isolated_setup_uninstalled": True,
                   "passed": True, "portable_sha256": digest_file(package), "setup_sha256": digest_file(setup)})
    (output / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
