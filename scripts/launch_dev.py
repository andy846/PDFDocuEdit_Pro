"""Start the Windows development app with this checkout's local environment."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4


def application_root() -> Path:
    return Path(__file__).resolve().parent.parent


def environment(root: Path) -> Path:
    python = root / ".venv-dev/Scripts/pythonw.exe"
    if not python.is_file() or not python.resolve().is_relative_to(root.resolve()):
        raise RuntimeError("Local .venv-dev is missing; follow docs/DEVELOPMENT_WORKSPACE.md.")
    if not (root / "main.py").is_file():
        raise RuntimeError("Development source main.py is missing.")
    return python


def launch(root: Path, arguments: list[str]) -> dict:
    root = root.resolve()
    python = environment(root)
    logs = root / "build/dev-launch/logs"
    if not logs.resolve().is_relative_to(root):
        raise RuntimeError("Development log directory escapes the checkout.")
    logs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + uuid4().hex[:8]
    stdout = logs / (stamp + ".stdout.log")
    stderr = logs / (stamp + ".stderr.log")
    with stdout.open("xb") as out, stderr.open("xb") as err:
        process = subprocess.Popen(
            [str(python), "-u", str(root / "main.py"), *arguments],
            cwd=root, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    return {"pid": process.pid, "root": str(root), "python": str(python),
            "stdout": str(stdout), "stderr": str(stderr)}


def main(arguments: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if arguments is None else arguments
    root = application_root()
    try:
        if arguments == ["--check"]:
            print(json.dumps({"root": str(root), "python": str(environment(root))}, indent=2))
        else:
            print(json.dumps(launch(root, arguments), indent=2))
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
