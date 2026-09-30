from __future__ import annotations

import json

import pytest

from composition.data.source import import_records, suggest_import
from composition.template.model import (
    CompositionError,
    DataConfig,
    Element,
    Template,
    parse_value,
    resolve_value,
)
from composition.template.serializer import load_project, save_project


def test_template_roundtrip_and_version(tmp_path):
    source = tmp_path / "data.csv"
    source.write_text("Name\nAlice\n", encoding="utf-8")
    template = Template(elements=[Element(value="Hello {{Name}}")], data=DataConfig(str(source)))
    target = save_project(template, tmp_path / "customer.pdcx")
    loaded = load_project(target)
    assert loaded.elements[0].value == "Hello {{Name}}"
    assert loaded.data.path == str(source)
    value = json.loads(target.read_text(encoding="utf-8"))
    value["template_version"] = 900
    target.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(CompositionError, match="version"):
        load_project(target)


@pytest.mark.parametrize("value", [
    {"template_version": 1, "width_mm": -1},
    {"template_version": 1, "elements": [{"type": "script"}]},
    {"template_version": 1, "unknown": 1},
    {"template_version": 1, "elements": [{"width_mm": float("nan")}]},
])
def test_reject_invalid_schema(value):
    with pytest.raises(CompositionError):
        Template.from_dict(value)


def test_variable_parser_is_declarative():
    assert resolve_value(parse_value("Balance: {{Balance}}"), {"Balance": "00100.00"}) == "Balance: 00100.00"
    with pytest.raises(CompositionError, match="Missing field"):
        resolve_value(parse_value("{{Unknown}}"), {})
    with pytest.raises(CompositionError, match="syntax"):
        parse_value("{{__import__('os')}}")


def test_csv_bom_quotes_multiline_and_empty_fields(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text('Customer Name,Account,Note\nAlice,00012,"line one\nline two"\nBob,00013,\n', encoding="utf-8-sig", newline="")
    config = suggest_import(source)
    store = import_records(config, tmp_path / "records.db")
    assert store.count == 2
    assert store.fields == ["Customer_Name", "Account", "Note"]
    assert store.metadata["original_fields"] == ["Customer Name", "Account", "Note"]
    assert store.record(1)["Note"] == "line one\nline two"
    assert store.record(2)["Note"] == ""
    assert list(store.records())[0][1]["Account"] == "00012"


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "big5", "gb18030"])
def test_unicode_encodings(tmp_path, encoding):
    source = tmp_path / "source.txt"
    source.write_text("Name\tCode\n\u9999\u6e2f\t001\n", encoding=encoding)
    store = import_records(DataConfig(str(source), encoding, "\t"), tmp_path / "records.db")
    assert store.record(1)["Name"] == "\u9999\u6e2f"


def test_no_header_and_malformed_records(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("Alice|01\nBob|02\n", encoding="utf-8")
    store = import_records(DataConfig(str(source), "utf-8", "|", False), tmp_path / "records.db")
    assert store.count == 2
    assert store.record(1)["Field_1"] == "Alice"
    source.write_text("Name,Code\nAlice\n", encoding="utf-8")
    with pytest.raises(CompositionError, match="Record 1"):
        import_records(DataConfig(str(source)), tmp_path / "bad.db")
    assert not (tmp_path / "bad.db").exists()


def test_normalization_collisions_require_mapping(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("Account No,Account-No\n01,02\n", encoding="utf-8")
    with pytest.raises(CompositionError, match="unique"):
        import_records(DataConfig(str(source)), tmp_path / "bad.db")
    config = DataConfig(str(source), mapping={"Account-No": "Other"})
    store = import_records(config, tmp_path / "good.db")
    assert store.fields == ["Account_No", "Other"]


def test_cancel_does_not_leave_snapshot(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("Name\nAlice\n", encoding="utf-8")
    target = tmp_path / "cancel.db"
    with pytest.raises(CompositionError, match="cancelled"):
        import_records(DataConfig(str(source)), target, is_cancelled=lambda: True)
    assert not target.exists()
