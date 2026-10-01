from __future__ import annotations

import copy
import json
from dataclasses import asdict
from pathlib import Path

import fitz
import pytest
from PIL import Image

from composition.data.source import RecordStore, import_records
from composition.engine.renderer import render_preview
from composition.engine.rules import CompiledGroup, ElementPlan
from composition.production.generator import generate, reconcile
from composition.production.model import JobResult, ProductionJob
from composition.template.model import (
    AlternativeContent,
    CompositionError,
    ConditionGroup,
    DataConfig,
    Element,
    ElementRules,
    FontSpec,
    PageSpec,
    RuleCondition,
    Template,
    required_fields,
)
from composition.template.serializer import load_project, save_project
from composition.worker import dispatch


def group(field="Scheme_Code", value="GS", operator="eq", data_type="text", mode="all"):
    return ConditionGroup(mode, [RuleCondition(field, operator, data_type, value)])


@pytest.mark.parametrize(
    ("operator", "value", "expected", "matches"),
    [
        ("eq", "001", "001", True),
        ("eq", "001", "1", False),
        ("ne", "001", "1", True),
        ("contains", "A GS B", "GS", True),
        ("starts_with", "GS-1", "GS", True),
        ("ends_with", "1-GS", "GS", True),
        ("eq", "gs", "GS", False),
        ("is_empty", "", "", True),
        ("not_empty", " ", "", True),
    ],
)
def test_exact_text_comparisons(operator, value, expected, matches):
    assert CompiledGroup(group(value=expected, operator=operator)).matches({"Scheme_Code": value}) is matches


@pytest.mark.parametrize(
    ("operator", "value", "expected", "matches"),
    [
        ("gt", "10000.01", "10000", True),
        ("gt", "10000", "10000", False),
        ("ge", "10000", "10000", True),
        ("lt", "-0.01", "0", True),
        ("le", "0.1", "0.100", True),
        ("eq", "0001.00", "1", True),
        ("ne", "9007199254740993", "9007199254740992", True),
        ("gt", "9007199254740993", "9007199254740992", True),
        ("eq", " +.5 ", "0.50", True),
    ],
)
def test_decimal_comparisons_without_float_rounding(operator, value, expected, matches):
    assert (
        CompiledGroup(group("Balance", expected, operator, "number")).matches({"Balance": value}) is matches
    )


@pytest.mark.parametrize("bad", ["", "NaN", "Infinity", "1,000", "$100", "1e4", "1_000", "9" * 129])
def test_bad_numeric_values_are_explicit_errors(bad):
    with pytest.raises(CompositionError, match="Field Balance.*finite decimal"):
        CompiledGroup(group("Balance", "100", "gt", "number")).matches({"Balance": bad})


def test_all_any_do_not_short_circuit_invalid_numeric_data():
    conditions = [RuleCondition("Scheme_Code", value="GS"), RuleCondition("Balance", "gt", "number", "100")]
    assert CompiledGroup(ConditionGroup("all", conditions)).matches({"Scheme_Code": "GS", "Balance": "101"})
    assert not CompiledGroup(ConditionGroup("all", conditions)).matches(
        {"Scheme_Code": "IS", "Balance": "101"}
    )
    assert CompiledGroup(ConditionGroup("any", conditions)).matches({"Scheme_Code": "IS", "Balance": "101"})
    with pytest.raises(CompositionError, match="Balance"):
        CompiledGroup(ConditionGroup("any", conditions)).matches({"Scheme_Code": "GS", "Balance": "bad"})
    with pytest.raises(CompositionError, match="Missing field"):
        CompiledGroup(ConditionGroup("all", conditions)).matches({"Scheme_Code": "IS"})


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_key",
        "nested_script",
        "bad_operator",
        "bad_mode",
        "empty_group",
        "too_many",
        "bad_type",
        "bad_field",
        "bad_threshold",
        "legacy_rules",
    ],
)
def test_untrusted_rule_schema_rejected(mutation):
    model = Template(elements=[Element(rules=ElementRules(visible_when=group()))])
    raw = model.to_dict()
    rule = raw["pages"][0]["elements"][0]["rules"]
    visible = rule["visible_when"]
    if mutation == "unknown_key":
        rule["script"] = "open('x','w')"
    elif mutation == "nested_script":
        visible["conditions"][0] = {"call": "os.system"}
    elif mutation == "bad_operator":
        visible["conditions"][0]["operator"] = "__import__"
    elif mutation == "bad_mode":
        visible["mode"] = "eval"
    elif mutation == "empty_group":
        visible["conditions"] = []
    elif mutation == "too_many":
        visible["conditions"] *= 21
    elif mutation == "bad_type":
        visible["conditions"][0]["data_type"] = "python"
    elif mutation == "bad_field":
        visible["conditions"][0]["field"] = "__import__('os')"
    elif mutation == "bad_threshold":
        visible["conditions"][0].update(data_type="number", value="NaN")
    elif mutation == "legacy_rules":
        raw["template_version"] = 3
        for key in ("sheet", "excel_formulas", "preserve_zeros"):
            raw["data"].pop(key)
        for key in ("sequences", "record_mode", "generated_count"):
            raw.pop(key)
    message = "Conditional rules require template version 4" if mutation == "legacy_rules" else None
    with pytest.raises(CompositionError, match=message):
        Template.from_dict(raw)


def test_literal_script_text_is_inert():
    literal = "__import__('os').system('never run')"
    model = Element(rules=ElementRules(visible_when=group(value=literal)))
    assert ElementPlan(model).resolve({"Scheme_Code": literal}).visible


def test_schema3_migration_preserves_exact_font_repair_and_output_pixels():
    model = Template(elements=[Element(value="Client standard \u7530", font=FontSpec(size_pt=11),
        vertical_align="center", height_mm=20, glyph_repairs={"U+7530": FontSpec(family="Noto Sans CJK HK")})])
    raw = model.to_dict()
    raw["template_version"] = 3
    for key in ("sheet", "excel_formulas", "preserve_zeros"):
        raw["data"].pop(key)
    raw["pages"][0]["elements"][0].pop("rules")
    for key in ("sequences", "record_mode", "generated_count"):
        raw.pop(key)
    before = copy.deepcopy(raw)
    migrated = Template.from_dict(raw)
    assert raw == before and migrated.template_version == 6
    assert migrated.elements[0].rules == ElementRules()
    assert asdict(migrated.elements[0].font) == asdict(model.elements[0].font)
    assert migrated.elements[0].glyph_repairs == model.elements[0].glyph_repairs
    old_pdf = render_preview(model, {})
    new_pdf = render_preview(migrated, {})
    with fitz.open(stream=old_pdf, filetype="pdf") as a, fitz.open(stream=new_pdf, filetype="pdf") as b:
        assert a[0].get_pixmap().samples == b[0].get_pixmap().samples


def test_references_in_conditions_and_both_content_branches_are_required():
    element = Element(
        value="{{Normal}}",
        rules=ElementRules(group("Visible", "Y"), AlternativeContent(group("Scheme", "GS"), "{{Other}}")),
    )
    assert required_fields(Template(elements=[element])) == {"Visible", "Scheme", "Normal", "Other"}
    with pytest.raises(CompositionError, match="Missing field"):
        ElementPlan(element).resolve({"Visible": "N", "Scheme": "GS", "Normal": ""})


def test_design_ignores_rules_record_preview_evaluates_and_keeps_fixed_pages(tmp_path):
    model = Template(
        pages=[
            PageSpec(
                elements=[Element(value="Base", rules=ElementRules(group("Balance", "10", "gt", "number")))]
            ),
            PageSpec(elements=[Element(value="Second", rules=ElementRules(group(value="GS")))]),
        ]
    )
    raw = render_preview(model, {"Balance": "{{Balance}}", "Scheme_Code": "{{Scheme_Code}}"}, design=True)
    with fitz.open(stream=raw, filetype="pdf") as document:
        assert "Base" in document[0].get_text() and "Second" in document[1].get_text()
    details = []
    raw = render_preview(model, {"Balance": "0", "Scheme_Code": "IS"}, rule_details=details)
    with fitz.open(stream=raw, filetype="pdf") as document:
        assert document.page_count == 2 and not document[0].get_text() and not document[1].get_text()
    assert len(details) == 2 and all(not item["visible"] for item in details)
    # Worker Design must not compare a numeric placeholder.
    result = dispatch(
        {"task": "preview", "template": model.to_dict(), "target": str(tmp_path / "design.pdf"), "page": 0}
    )
    assert result["rules"] == []
    assert Path(result["image"]).is_file()


def production_case(tmp_path, count=8):
    red, blue = tmp_path / "red.png", tmp_path / "blue.png"
    Image.new("RGB", (16, 16), "red").save(red)
    Image.new("RGB", (16, 16), "blue").save(blue)
    text = Element(
        value="Normal {{Name}}",
        height_mm=20,
        vertical_align="center",
        glyph_repairs={"U+7530": FontSpec(family="Noto Sans CJK HK")},
        rules=ElementRules(alternative=AlternativeContent(group(), "Special \u7530 {{Name}}")),
    )
    hidden = Element(value="\u7530", y_mm=60, rules=ElementRules(group("Balance", "10000", "gt", "number")))
    image = Element(
        type="image",
        image=str(red),
        width_mm=20,
        height_mm=20,
        rules=ElementRules(alternative=AlternativeContent(group(), image=str(blue))),
    )
    model = Template(pages=[PageSpec(elements=[text, hidden]), PageSpec(elements=[image])])
    source = tmp_path / "source.csv"
    source.write_text(
        "Name,Scheme_Code,Balance\n"
        + "".join(f"Client{i},{'GS' if i % 2 == 0 else 'IS'},0\n" for i in range(count)),
        encoding="utf-8",
    )
    model.data.path = str(source)
    store = import_records(DataConfig(path=str(source)), tmp_path / "records.db")
    return model, store


def test_production_selected_branches_glyph_audit_images_and_reconciliation(tmp_path):
    model, store = production_case(tmp_path)
    primary = asdict(model.elements[0].font)
    result = generate(ProductionJob(model.to_dict(), str(store.path), str(tmp_path / "output"), chunk_size=3))
    assert result.status == "completed", result.error
    assert (result.input_records, result.successful_records, result.generated_pages) == (8, 8, 16)
    assert result.repaired_records == result.repaired_glyphs == 4
    assert result.rule_summary == {
        "configured_objects": 3,
        "records_checked": 8,
        "hidden_occurrences": 8,
        "alternate_occurrences": 8,
        "complete": True,
    }
    with fitz.open(result.output_pdf) as output:
        assert "Special" in output[0].get_text() and "Normal" in output[2].get_text()
        assert output[1].get_pixmap().pixel(85, 85) == (0, 0, 255)
        assert output[3].get_pixmap().pixel(85, 85) == (255, 0, 0)
        preview = render_preview(model, store.record(1))
        with fitz.open(stream=preview, filetype="pdf") as shown:
            for page in range(2):
                assert output[page].get_pixmap().samples == shown[page].get_pixmap().samples
    assert asdict(model.elements[0].font) == primary
    report = json.loads((Path(result.report_dir) / "job.json").read_text(encoding="utf-8"))
    assert report["rule_summary"] == result.rule_summary and report["job_version"] == 2
    assert "Rules Checked Records" in (Path(result.report_dir) / "control.csv").read_text(
        encoding="utf-8-sig"
    )


def test_alternative_assets_saved_and_reopened_as_independent_copies(tmp_path):
    model, _store = production_case(tmp_path)
    before = {
        path: Path(path).read_bytes()
        for path in (model.pages[1].elements[0].image, model.pages[1].elements[0].rules.alternative.image)
    }
    project = save_project(model, tmp_path / "saved.pdcx")
    loaded = load_project(project)
    image = loaded.pages[1].elements[0]
    assert ".assets" in image.image and ".assets" in image.rules.alternative.image
    assert Path(image.image).read_bytes() == before[model.pages[1].elements[0].image]
    assert (
        Path(image.rules.alternative.image).read_bytes()
        == before[model.pages[1].elements[0].rules.alternative.image]
    )
    assert (
        model.to_dict()["pages"][0]["elements"][0]["rules"]
        == loaded.to_dict()["pages"][0]["elements"][0]["rules"]
    )
    for path, value in before.items():
        assert Path(path).read_bytes() == value


def test_invalid_numeric_record_stops_before_composition_and_identifies_record(tmp_path):
    model, store = production_case(tmp_path)
    # Build a second snapshot with the later invalid numeric field; preserve first source.
    source = tmp_path / "bad.csv"
    source.write_text("Name,Scheme_Code,Balance\nFirst,IS,0\nSecond,IS,private-bad-value\n", encoding="utf-8")
    bad = import_records(DataConfig(path=str(source)), tmp_path / "bad.db")
    result = generate(ProductionJob(model.to_dict(), str(bad.path), str(tmp_path / "output")))
    assert result.status == "failed" and result.error_record == 2
    assert result.successful_records == result.generated_pages == result.generated_files == 0
    assert result.failed_records == result.processed_records == 1
    assert "Record 2" in result.error and "Balance" in result.error
    assert "private-bad-value" not in result.error
    assert result.rule_summary["records_checked"] == 1 and not result.rule_summary["complete"]
    assert not list(Path(result.report_dir).glob("*.pdf"))
    assert store.count == 8


def test_cancellation_in_rules_preflight_never_publishes(tmp_path, monkeypatch):
    model, store = production_case(tmp_path)
    original = RecordStore.records
    state = {"cancel": False}

    def records(self):
        for ordinal, record in original(self):
            state["cancel"] = ordinal == 2
            yield ordinal, record

    monkeypatch.setattr(RecordStore, "records", records)
    result = generate(
        ProductionJob(model.to_dict(), str(store.path), str(tmp_path / "output")),
        is_cancelled=lambda: state["cancel"],
    )
    assert result.status == "cancelled" and result.generated_files == 0
    assert result.rule_summary["records_checked"] == 1 and not result.rule_summary["complete"]
    assert not list(Path(result.report_dir).glob("*.pdf"))


def test_hidden_image_still_requires_valid_declared_asset(tmp_path):
    model = Template(
        elements=[
            Element(
                type="image", image=str(tmp_path / "missing.png"), rules=ElementRules(visible_when=group())
            )
        ]
    )
    with pytest.raises(CompositionError, match="Image not found"):
        render_preview(model, {"Scheme_Code": "IS"})


def test_reconciliation_rejects_incomplete_rule_scan():
    result = JobResult(
        "test",
        input_records=1,
        processed_records=1,
        successful_records=1,
        expected_pages=1,
        generated_pages=1,
        generated_files=1,
        rule_summary={"complete": False, "records_checked": 1},
    )
    with pytest.raises(CompositionError, match="RECONCILIATION FAILED"):
        reconcile(result)
