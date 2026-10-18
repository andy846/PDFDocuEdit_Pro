"""The development entry point must use its own checkout and environment."""
import json
from pathlib import Path

import pytest

from scripts import launch_dev


def workspace(tmp_path):
    root = tmp_path / "Project with spaces"
    (root / ".venv-dev/Scripts").mkdir(parents=True)
    (root / ".venv-dev/Scripts/pythonw.exe").touch()
    (root / "main.py").write_text("", encoding="utf-8")
    return root


def test_launch_uses_local_python_and_preserves_document_arguments(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    calls = []

    def spawn(args, **kwargs):
        calls.append((args, kwargs))
        return type("Process", (), {"pid": 1234})()

    monkeypatch.setattr(launch_dev.subprocess, "Popen", spawn)
    result = launch_dev.launch(root, ["C:/Input with spaces/example.pdcx"])
    args, options = calls[0]
    assert args == [str(root / ".venv-dev/Scripts/pythonw.exe"), "-u", str(root / "main.py"),
                    "C:/Input with spaces/example.pdcx"]
    assert options["cwd"] == root
    assert options["stdin"] == launch_dev.subprocess.DEVNULL
    assert options["creationflags"] == getattr(launch_dev.subprocess, "CREATE_NO_WINDOW", 0)
    assert result["pid"] == 1234
    assert all(Path(result[key]).parent == root / "build/dev-launch/logs" for key in ("stdout", "stderr"))


def test_missing_environment_fails_before_log_creation(tmp_path):
    (tmp_path / "main.py").touch()
    with pytest.raises(RuntimeError, match="venv-dev"):
        launch_dev.launch(tmp_path, [])
    assert not (tmp_path / "build").exists()


def test_logs_are_exclusively_created_for_each_launch(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    monkeypatch.setattr(launch_dev.subprocess, "Popen", lambda *a, **k: type("P", (), {"pid": 1})())
    first = launch_dev.launch(root, [])
    second = launch_dev.launch(root, [])
    assert first["stdout"] != second["stdout"]
    assert Path(first["stdout"]).is_file() and Path(second["stderr"]).is_file()


def test_check_does_not_start_application(tmp_path, monkeypatch, capsys):
    root = workspace(tmp_path)
    monkeypatch.setattr(launch_dev, "application_root", lambda: root)
    monkeypatch.setattr(launch_dev.subprocess, "Popen", lambda *a, **k: pytest.fail("check launched an application"))
    assert launch_dev.main(["--check"]) == 0
    assert json.loads(capsys.readouterr().out)["root"] == str(root)
    assert not (root / "build").exists()
