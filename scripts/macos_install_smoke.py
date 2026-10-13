"""Exercise the copied .app without build-time runtime search paths."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

from scripts.prepare_macos import require_arm64


def run(app, output):
    require_arm64()
    output = Path(output).resolve()
    installed = output / "Installation with spaces" / "PDFDocuEdit Pro.app"
    shutil.copytree(app, installed, symlinks=True)
    executable = installed / "Contents/MacOS/PDFDocuEdit Pro"
    environment = {k: v for k, v in os.environ.items() if not k.startswith(("DYLD_", "PYTHON", "GS_"))}
    environment.update(PATH="/usr/bin:/bin:/usr/sbin:/sbin", PDFDOCUEDIT_COMPOSITION_QA="1",
                       QT_QPA_PLATFORM="offscreen", PYINSTALLER_RESET_ENVIRONMENT="1")
    for file in installed.rglob("*"):
        if not file.is_file() or file.is_symlink():
            continue
        with file.open("rb") as stream:
            magic = stream.read(4)
        if magic not in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe"):
            continue
        dependencies = subprocess.check_output(["otool", "-L", str(file)], text=True)
        for line in dependencies.splitlines()[1:]:
            dependency = line.strip().split(" (", 1)[0]
            if dependency.startswith("/") and not dependency.startswith(("/usr/lib/", "/System/Library/")):
                raise RuntimeError(f"Bundle has a build-machine dependency: {file}\n{dependencies}")
        if subprocess.check_output(["lipo", "-archs", str(file)], text=True).strip() != "arm64":
            raise RuntimeError(f"Bundle contains an unexpected native architecture: {file}")
    with (output / "frozen.log").open("w") as log:
        subprocess.run([str(executable), "--macos-smoke", str(output / "results")], cwd=output,
                       env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=600, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.app, args.output)
