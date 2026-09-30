"""Install and remove a QA-only payload without registering PDF handlers or shortcuts."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.build import ROOT, _find_inno_setup_compiler


def run():
    compiler = _find_inno_setup_compiler()
    if not compiler:
        raise RuntimeError("Inno Setup 6 is required for the installed-build acceptance.")
    directory = (ROOT / "build" / "composition-install-qa").resolve()
    installation = directory / "installed"
    if not directory.is_relative_to(ROOT.resolve()) or not installation.is_relative_to(directory):
        raise RuntimeError("Unsafe QA installation directory.")
    directory.mkdir(parents=True, exist_ok=True)
    source = ROOT / "dist" / "PDFDocuEdit Pro"
    script = directory / "qa.iss"
    # QA gets its own uninstall identity. No global file-handler/shortcut changes.
    script.write_text(f'''[Setup]
AppId=PDFDocuEdit-Composition-Local-QA
AppName=PDFDocuEdit Composition Local QA
AppVersion=2.5.15
DefaultDirName={installation}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={directory}
OutputBaseFilename=Composition-Local-QA
Compression=zip/1
SolidCompression=no
DisableDirPage=yes
DisableProgramGroupPage=yes
UsePreviousAppDir=no
CloseApplications=no
RestartApplications=no
[Files]
Source: "{source}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs
''', encoding="utf-8")
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    with (directory / "compile.log").open("w", encoding="utf-8") as log:
        subprocess.run([str(compiler), str(script)], check=True, stdout=log,
                       stderr=subprocess.STDOUT, **options)
    setup = directory / "Composition-Local-QA.exe"
    subprocess.run([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
                    f"/LOG={directory/'install.log'}"], check=True, **options)
    try:
        executable = installation / "PDFDocuEdit Pro.exe"
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
        environment["PDFDOCUEDIT_COMPOSITION_QA"] = "1"
        environment.pop("PDFDOCUEDIT_ENABLE_COMPOSITION", None)
        output = directory / "acceptance"
        subprocess.run([str(executable), "--composition-smoke", str(output)], cwd=installation,
                       env=environment, check=True, timeout=180, **options)
        result = json.loads((output / "result.json").read_text(encoding="utf-8"))
        if not result["passed"]:
            raise RuntimeError("Installed composition acceptance failed.")
        (directory / "result.json").write_text(json.dumps(
            {"installed_build_passed": True, "installation": str(installation),
             "isolated_app_id": "PDFDocuEdit-Composition-Local-QA",
             "registered_pdf_handlers": False, "acceptance": result}, indent=2), encoding="utf-8")
        print("Installed composition acceptance passed.")
    finally:
        uninstaller = installation / "unins000.exe"
        if uninstaller.exists():
            subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                            f"/LOG={directory/'uninstall.log'}"], check=True, **options)
    print("QA-only installation removed.")


if __name__ == "__main__":
    run()
