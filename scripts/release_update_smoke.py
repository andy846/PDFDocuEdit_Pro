"""Real-binary managed upgrade in a fresh directory; scripted restart, no user files."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))

import launcher  # noqa: E402
from core.resources import APP_VERSION  # noqa: E402
from scripts.build_managed_installer import extract_deployment  # noqa: E402
from updates.protocol import Manifest, atomic_json, digest_file  # noqa: E402
from updates.runtime import Installation  # noqa: E402
from updates.trust import PUBLIC_KEY_HEX  # noqa: E402


def run(baseline,baseline_version,release,output):
    if sys.platform!="win32":
        raise RuntimeError("Real-binary acceptance requires Windows")
    output=Path(output).resolve()
    root=output/"PDFDocuEditPro"
    if root.exists():
        raise RuntimeError("Use a fresh upgrade acceptance directory")
    baseline=Path(baseline).resolve()
    checksum=baseline.with_suffix(baseline.suffix+".sha256").read_text(encoding="utf-8").split()[0]
    if digest_file(baseline)!=checksum:
        raise RuntimeError("Baseline deployment checksum mismatch")
    output.mkdir(parents=True,exist_ok=True)
    extract_deployment(baseline,output,baseline_version)
    installation=Installation(root)
    (root/"data"/".migration-complete").touch()
    sentinel=root/"data"/"preserve-test.txt"
    sentinel.write_text("Preserve isolated user data",encoding="utf-8")
    release=Path(release).resolve()
    for name in ("update.json","update.sig"):
        shutil.copyfile(release/name,root/"staging"/name)
    manifest=Manifest.verify((root/"staging"/"update.json").read_bytes(),
                             (root/"staging"/"update.sig").read_bytes(),PUBLIC_KEY_HEX)
    if manifest.version!=APP_VERSION:
        raise RuntimeError("Update manifest version mismatch")
    shutil.copyfile(release/manifest.asset,root/"staging"/"package.zip")
    manifest.verify_archive(root/"staging"/"package.zip")
    launched,failures,threads=[],[],[]
    previous_notify=launcher.notify
    launcher.notify=failures.append

    def spawn(arguments,**kwargs):
        target=Path(arguments[0]).parent.name
        launched.append(target)
        environment=kwargs["env"].copy()
        environment["QT_QPA_PLATFORM"]="offscreen"
        environment.pop("PDFDOCUEDIT_ENABLE_COMPOSITION",None)
        child=subprocess.Popen(arguments,**{**kwargs,"env":environment})
        token=environment["PDFDOCUEDIT_LAUNCH_TOKEN"]

        def finish():
            import _winapi

            try:
                deadline=time.monotonic()+100
                accepted=root/f"accepted-{token}.json"
                while not accepted.exists():
                    if child.poll() is not None:
                        raise RuntimeError(f"{target} exited before readiness")
                    if time.monotonic()>deadline:
                        raise TimeoutError(f"{target} readiness timed out")
                    time.sleep(.1)
                if target==baseline_version:
                    atomic_json(root/"restart.json",{"token":token})
                # These are this harness's empty-document children, after the
                # actual app/launcher handshake. Never stop an existing process.
                _winapi.TerminateProcess(child._handle,75 if target==baseline_version else 0)
            except Exception as exc:
                failures.append(str(exc))
                if child.poll() is None:
                    child.terminate()
        thread=threading.Thread(target=finish)
        thread.start()
        threads.append(thread)
        return child

    try:
        result=launcher.supervise(installation,[],spawn=spawn,timeout=110)
        for thread in threads:
            thread.join(10)
    finally:
        launcher.notify=previous_notify
    expected={"current":APP_VERSION,"previous":baseline_version,"phase":"stable"}
    if failures or result or launched!=[baseline_version,APP_VERSION] or installation.state()!=expected:
        raise RuntimeError(f"Upgrade failed: {failures}; launches={launched}; state={installation.state()}")
    if sentinel.read_text(encoding="utf-8")!="Preserve isolated user data":
        raise RuntimeError("User data was not retained")
    report={"passed":True,"launched":launched,"state":expected,"real_frozen_applications":True,
            "supervisor":"current source protocol","restart_request":"scripted",
            "settings_preserved":True,"signed_update_verified":True,"output":str(output)}
    (output/"result.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline",required=True,type=Path)
    parser.add_argument("--baseline-version",default="2.5.16")
    parser.add_argument("--release",default=ROOT/"release",type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    run(args.baseline,args.baseline_version,args.release,args.output)
