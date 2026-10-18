"""Portable v1 rules retain detection semantics without saving job results."""
import json
from pathlib import Path

import pytest

from composition.pdf_source.detection import DetectionConfig, detect_texts
from composition.pdf_source.profiles import load_profile, save_profile
from composition.template.model import CompositionError


@pytest.mark.parametrize("rules,texts,want", [
    ([{"kind": "region_present"}], ["First", "", "Second", ""], [[1, 2], [3, 4]]),
    ([{"kind": "page_number", "pattern": "Page {CURRENT} of {TOTAL}"}],
     ["Page 1 of 2", "Page 2 of 2", "Page 1 of 2", "Page 2 of 2"], [[1, 2], [3, 4]]),
    ([{"kind": "first_text", "terms": ["Dear"]}], ["Dear", "Body", "Dear", "Body"], [[1, 2], [3, 4]]),
    ([{"kind": "document_id", "pattern": "Account: {ID}"}],
     ["Account: A", "Account: A", "Account: B", "Account: B"], [[1, 2], [3, 4]]),
    ([{"kind": "separator", "terms": ["SEPARATOR"]}],
     ["First", "Body", "SEPARATOR", "Second"], [[1, 2], [4, 4]]),
    ([{"kind": "region_present"}, {"kind": "first_text", "terms": ["Dear"]}],
     ["Dear", "Body", "Dear", "Body"], [[1, 2], [3, 4]]),
])
def test_v1_profile_roundtrip_preserves_exact_grouping(tmp_path, rules, texts, want):
    config = DetectionConfig(rules=rules, region_mm=[8, 19, 70, 8], combine="all")
    path = save_profile(tmp_path / "reusable.pdmp", config)
    loaded = DetectionConfig(**load_profile(path))
    result = detect_texts(texts, loaded)
    assert result["groups"] == want and not result["accepted"]
    assert loaded.rules == rules and loaded.region_mm == [8, 19, 70, 8]
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    assert set(raw) == {"profile_version", "config"}
    assert set(raw["config"]) == {"rules", "combine", "region_mm", "remove_separators", "version", "profile_name"}


def test_invalid_v1_profile_cannot_be_saved_or_loaded(tmp_path):
    path = tmp_path / "invalid.pdmp"
    config = DetectionConfig(rules=[{"kind": "region_present"}])
    with pytest.raises(CompositionError, match="selected search region"):
        save_profile(path, config)
    assert not path.exists()
    path.write_text(json.dumps({"profile_version": 1, "config": {"rules": [{"kind": "region_present"}]}}))
    with pytest.raises(CompositionError, match="selected search region"):
        load_profile(path)


@pytest.mark.parametrize("name", [{"unexpected": "object"}, "X" * 121])
def test_invalid_profile_name_rejected_before_ui_callback(tmp_path, name):
    from dataclasses import asdict

    config = DetectionConfig(rules=[{"kind": "region_present"}], region_mm=[8, 19, 70, 8], profile_name=name)
    path = tmp_path / "bad-name.pdmp"
    with pytest.raises(CompositionError, match="profile name"):
        save_profile(path, config)
    assert not path.exists()
    path.write_text(json.dumps({"profile_version": 1, "config": asdict(config)}))
    with pytest.raises(CompositionError, match="profile name"):
        load_profile(path)
