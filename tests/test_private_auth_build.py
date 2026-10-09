from pathlib import Path

import pytest

from scripts.distribution_safety import assert_public_distribution, is_public_ca
from scripts.make_windows_build_kit import allowed_files


def test_build_kit_only_tracked_source_and_explicit_runtime(tmp_path):
    files = ("main.py", "secret/private.pdf", ".update-keys/signing.pem", "config.json", "run.log", ".env",
             ".venv-312/Lib/private.py", ".venv-tools/Lib/private.py", ".idea/private.xml", "personal.pdf",
             "Ghostscript/bin/gswin64c.exe", "Ghostscript/doc/COPYING")
    for relative in files:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    included = {p.relative_to(tmp_path).as_posix() for p in allowed_files(tmp_path, tracked=[Path(p) for p in files if p != "personal.pdf"])}
    assert included == {"main.py", "Ghostscript/bin/gswin64c.exe", "Ghostscript/doc/COPYING"}


def test_ca_allowance_is_exact_path_content_and_certificates(tmp_path):
    certifi = pytest.importorskip("certifi")
    path = tmp_path / "_internal/certifi/cacert.pem"
    path.parent.mkdir(parents=True)
    path.write_bytes(Path(certifi.where()).read_bytes())
    assert is_public_ca(path, path.relative_to(tmp_path))
    assert_public_distribution(tmp_path)
    assert not is_public_ca(path, Path("signing.pem"))
    path.write_bytes(b"-----BEGIN PRIVATE KEY-----\nprivate")
    with pytest.raises(ValueError, match="Private/local"):
        assert_public_distribution(tmp_path)


def test_private_parent_path_rejected(tmp_path):
    path = tmp_path / "_internal/secret/private.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"private")
    with pytest.raises(ValueError, match="Private/local"):
        assert_public_distribution(tmp_path)
