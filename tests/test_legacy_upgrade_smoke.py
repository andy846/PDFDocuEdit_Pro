import zipfile
from unittest.mock import Mock

import pytest

from scripts import legacy_upgrade_smoke as helper
from updates.protocol import UpdateError


def test_long_qa_path_is_rejected_before_starting_frozen_launcher(tmp_path):
    package = tmp_path / "package.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("_internal/" + "nested/" * 20 + "resource.xsl", b"fixture")
    with pytest.raises(UpdateError, match="shorter QA"):
        helper.check_qa_paths(tmp_path, [package])


def test_failed_upgrade_cleanup_finds_prior_owned_child(tmp_path, monkeypatch):
    parent = Mock(pid=123)
    parent.poll.return_value = None
    observed = []
    stopped = []

    def child_of(pid, expected):
        observed.append((pid, expected))
        return 456 if expected.parent.name == "3.0.3" else None

    monkeypatch.setattr(helper, "child_of", child_of)
    monkeypatch.setattr(helper, "stop_owned", lambda pid, code: stopped.append((pid, code)))
    helper.cleanup_test_process(parent, tmp_path, ["3.0.3", "3.0.4"], None)
    assert observed == [(123, tmp_path / "versions/3.0.3/PDFDocuEdit Pro.exe")]
    assert stopped == [(456, 1)]
    parent.terminate.assert_called_once()
    parent.wait.assert_called_once_with(15)


def test_exited_test_parent_does_not_scan_or_stop_other_apps(tmp_path, monkeypatch):
    parent = Mock(pid=123)
    parent.poll.return_value = 0
    scan = Mock()
    stop = Mock()
    monkeypatch.setattr(helper, "child_of", scan)
    monkeypatch.setattr(helper, "stop_owned", stop)
    helper.cleanup_test_process(parent, tmp_path, ["3.0.3"], None)
    scan.assert_not_called()
    stop.assert_not_called()
    parent.terminate.assert_not_called()
