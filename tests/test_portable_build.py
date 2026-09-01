import pytest

from scripts.build import (
    _clean_portable_tree,
    _inno_signing_args,
    _windows_signing_settings,
)


def test_portable_cleanup_preserves_native_runtime_files(tmp_path):
    root = tmp_path / "PDFDocuEdit Pro"
    native_module = root / "_internal" / "PyQt6" / "QtCore.pyd"
    runtime_library = root / "_internal" / "numpy" / ".libs" / "openblas.dll"
    bytecode = root / "_internal" / "package" / "__pycache__" / "module.pyc"
    pytest_cache = root / ".pytest_cache" / "cache"
    debug_log = root / "debug.log"

    for path in (native_module, runtime_library, bytecode, pytest_cache, debug_log):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test")

    _clean_portable_tree(root)

    assert native_module.is_file()
    assert runtime_library.is_file()
    assert not bytecode.exists()
    assert not pytest_cache.exists()
    assert not debug_log.exists()


def test_windows_signing_settings_require_complete_configuration(monkeypatch):
    monkeypatch.setenv("PDFDOCUEDIT_SIGNTOOL", "C:/Tools/signtool.exe")
    monkeypatch.delenv("PDFDOCUEDIT_CERT_SHA1", raising=False)

    with pytest.raises(RuntimeError, match="Set both"):
        _windows_signing_settings()


def test_inno_signing_args_sign_setup_and_uninstaller(monkeypatch):
    monkeypatch.setenv("PDFDOCUEDIT_SIGNTOOL", "C:/Program Files/SDK/signtool.exe")
    monkeypatch.setenv("PDFDOCUEDIT_CERT_SHA1", "ABC123")
    monkeypatch.setenv("PDFDOCUEDIT_TIMESTAMP_URL", "https://timestamp.example.test")

    settings = _windows_signing_settings()
    args = _inno_signing_args(settings)

    assert args[1] == "/DMySignTool=pdfdocuedit_authenticode"
    assert "$qC:/Program Files/SDK/signtool.exe$q" in args[0]
    assert "/sha1 ABC123" in args[0]
    assert "/tr https://timestamp.example.test" in args[0]
    assert args[0].endswith("$f")
