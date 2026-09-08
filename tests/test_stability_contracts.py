from pathlib import Path

import pytest

import core.capabilities as capabilities
import core.verapdf as verapdf
from scripts import build


@pytest.mark.parametrize("name", ["verapdf", "VeraPDF"])
@pytest.mark.parametrize("frozen", [False, True])
def test_verapdf_discovery_is_shared(tmp_path, monkeypatch, name, frozen):
    root = tmp_path / "bundle"
    root.mkdir()
    executable = tmp_path / "app" / "editor.exe"
    base = executable.parent if frozen else root
    launcher = base / name / "verapdf.bat"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("test", encoding="utf-8")
    monkeypatch.setattr(verapdf, "bundle_root", lambda: root)
    monkeypatch.setattr(verapdf.sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(verapdf.sys, "executable", str(executable))
    monkeypatch.setattr(verapdf.platform, "system", lambda: "Windows")
    monkeypatch.setattr(verapdf.shutil, "which", lambda _: None)
    monkeypatch.setattr(capabilities, "_configured_executable", lambda _: None)
    runtime = verapdf.find_verapdf_runtime()
    capability = capabilities._verapdf_capability()
    assert runtime is not None
    assert Path(runtime.launcher).samefile(launcher)
    assert capability.available
    assert capability.path == runtime.launcher


@pytest.mark.parametrize("version", [(3, 11, 9), (3, 13, 0), (3, 14, 0)])
def test_build_rejects_unsupported_python_before_any_work(monkeypatch, version):
    monkeypatch.setattr(build.sys, "version_info", version)
    monkeypatch.setattr(build, "run", lambda *a, **k: pytest.fail("Build started"))
    with pytest.raises(RuntimeError, match="requires Python 3.12.x"):
        build.main()


def test_build_accepts_python_312(monkeypatch):
    monkeypatch.setattr(build.sys, "version_info", (3, 12, 9))
    monkeypatch.setattr(build, "run", lambda *a, **k: None)
    monkeypatch.setattr(build.platform, "system", lambda: "Windows")
    monkeypatch.setattr(build, "build_windows", lambda: ("setup", "portable"))
    assert build.main() == 0


def test_macos_ocr_contract(monkeypatch, capsys):
    monkeypatch.setattr(capabilities.platform, "system", lambda: "Darwin")
    assert capabilities.bundled_tesseract_runtime() == (
        None, None, "OCR is not bundled in the macOS build."
    )
    class StopBuild(Exception):
        pass
    def stop():
        raise StopBuild
    monkeypatch.setattr(build, "validate_verapdf_bundle", stop)
    with pytest.raises(StopBuild):
        build.build_macos()
    assert "OCR is not bundled in the macOS build." in capsys.readouterr().out


@pytest.mark.parametrize("version", [(3, 11, 9), (3, 13, 0)])
def test_source_verifier_has_same_python_contract(monkeypatch, capsys, version):
    from scripts import verify_source

    monkeypatch.setattr(verify_source.sys, "version_info", version)
    assert verify_source.main() == 1
    assert "Builds require Python 3.12.x" in capsys.readouterr().out
