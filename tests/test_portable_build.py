from scripts.build import _clean_portable_tree


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
