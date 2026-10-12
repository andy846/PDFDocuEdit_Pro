
import pytest

from composition.template.model import CompositionError
from core.output_safety import contained_path, validate_identifier
from workflow.branch_engine import validate_branch_run


@pytest.mark.parametrize("value", ["../../outside", "../other", "C:\\temp\\outside", "\\\\server\\share", "a/../b", "a\\b", "CON", "nul", "COM1", "", None])
def test_untrusted_identity_rejected_before_io(tmp_path, value):
    with pytest.raises(ValueError):
        validate_identifier(value)
    run = dict(id="valid", batch_id="safe", jobs=[dict(id=value, source_id="source", branch_id="letters", approved=True, batch={})])
    with pytest.raises(CompositionError):
        validate_branch_run(run)
    assert list(tmp_path.iterdir()) == []


def test_valid_identity_and_output(tmp_path):
    identity = "20261013-001_abcd"
    assert validate_identifier(identity) == identity
    assert contained_path(tmp_path, "batch-" + identity, "job001") == tmp_path / ("batch-" + identity) / "job001"


def test_output_link_escape_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "output"
    root.mkdir()
    link = root / "batch-safe"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        import subprocess
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
        if made.returncode:
            pytest.skip("Host does not permit symlinks or junctions")
    try:
        with pytest.raises(ValueError, match="symlink or junction"):
            contained_path(root, "batch-safe", "job")
        assert list(outside.iterdir()) == []
    finally:
        link.rmdir() if link.is_dir() and not link.is_symlink() else link.unlink()


def test_branch_nested_identity_mismatch_rejected():
    from workflow.batch import BatchJob, BatchRun
    job = BatchJob(id="different")
    run = dict(id="valid", batch_id="safe", jobs=[dict(id="expected", source_id="source", branch_id="letters", approved=True,
                                                     batch=BatchRun(batch_id="safe", jobs=[job]).to_dict())])
    with pytest.raises(CompositionError, match="identities"):
        validate_branch_run(run)
