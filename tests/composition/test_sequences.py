from __future__ import annotations

import copy
import json

import fitz
import pytest
from PyQt6.QtWidgets import QApplication, QDialogButtonBox

from composition.data.sequences import CompositionRecords, sequence_record, sequence_value
from composition.data.source import import_records
from composition.designer.sequence_dialog import SequenceDialog
from composition.designer.workspace import CompositionWindow
from composition.engine.renderer import render_preview
from composition.production.generator import generate
from composition.production.model import ProductionJob
from composition.template.model import (
    CompositionError,
    ConditionGroup,
    DataConfig,
    Element,
    ElementRules,
    PageSpec,
    RuleCondition,
    SequenceSpec,
    Template,
)
from composition.template.serializer import load_project, save_project
from composition.worker import dispatch
from tests.composition.test_designer_controls import cleanup, wait


def model(count=4):
    return Template(
        record_mode="generated", generated_count=count,
        sequences=[SequenceSpec("Ticket", 100, 2, 5, "INV-", "-HK"),
                   SequenceSpec("PageSeq", 1, 1, 3, scope="page")],
        pages=[PageSpec(id="front", elements=[Element(value="{{Ticket}} / {{PageSeq}}", width_mm=150)]),
               PageSpec(id="back", elements=[Element(value="{{Ticket}} / {{PageSeq}}", width_mm=150)])],
    )


@pytest.mark.parametrize("seq,ordinal,page,expected", [
    (SequenceSpec(), 1, 0, "000001"),
    (SequenceSpec(start=98, step=5, padding=2), 2, 0, "103"),
    (SequenceSpec(start=-2, step=-2, padding=3, prefix="N"), 2, 0, "N-004"),
    (SequenceSpec(start=2, step=-2, padding=0), 2, 0, "0"),
    (SequenceSpec(start=9, step=3, scope="page"), 2, 1, "000018"),
    (SequenceSpec(prefix="ABC", suffix="-HK"), 5, 1, "ABC000005-HK"),
])
def test_exact_integer_format_and_scope(seq, ordinal, page, expected):
    assert sequence_value(seq, ordinal, page, 2) == expected


@pytest.mark.parametrize("change", [
    {"name": "Bad name"}, {"name": ""}, {"name": "1Seq"}, {"start": True}, {"start": 1.1},
    {"start": 10**19}, {"step": 0}, {"step": "1"}, {"padding": -1}, {"padding": 33},
    {"padding": False}, {"prefix": "\n"}, {"suffix": "X"*201}, {"scope": "random"},
])
def test_invalid_sequences_block_before_render(change):
    raw = model().to_dict()
    raw["sequences"][0].update(change)
    with pytest.raises(CompositionError):
        Template.from_dict(raw)


def test_schema_versions_and_declarative_save_restore(tmp_path):
    template = model()
    target = save_project(template, tmp_path/"tickets.pdcx")
    loaded = load_project(target)
    assert loaded.to_dict() == template.to_dict()
    assert json.loads(target.read_text(encoding="utf-8"))["template_version"] == 12
    legacy = Template(elements=[Element(value="Client unchanged")]).to_dict()
    legacy["template_version"] = 4
    for key in ("sheet", "excel_formulas", "preserve_zeros"):
        legacy["data"].pop(key)
    for key in ("sequences", "record_mode", "generated_count"):
        legacy.pop(key)
    migrated = Template.from_dict(legacy)
    assert not migrated.sequences and migrated.record_mode == "imported"
    with fitz.open(stream=render_preview(migrated, {}), filetype="pdf") as a, fitz.open(
        stream=render_preview(Template(elements=[Element(value="Client unchanged")]), {}), filetype="pdf"
    ) as b:
        assert a[0].get_pixmap().samples == b[0].get_pixmap().samples
    for change in ({"template_version": 4}, {"generated_count": True}, {"generated_count": 0},
                   {"generated_count": 1_000_001}, {"record_mode": "other"}):
        raw = template.to_dict()
        raw.update(change)
        with pytest.raises(CompositionError):
            Template.from_dict(raw)
    raw = template.to_dict()
    raw["sequences"].append(copy.deepcopy(raw["sequences"][0]))
    with pytest.raises(CompositionError, match="Duplicate"):
        Template.from_dict(raw)


def test_virtual_source_is_lazy_repeatable_and_bounded():
    template = model(1_000_000)
    records = CompositionRecords(template)
    iterator = records.records()
    assert next(iterator) == (1, {})
    assert next(iterator) == (2, {})
    assert next(records.records()) == (1, {})
    assert records.record(1_000_000) == {}
    assert sequence_record(template, {}, 1_000_000, 1)["PageSeq"] == "2000000"
    with pytest.raises(CompositionError):
        records.record(1_000_001)
    assert not hasattr(records, "all_records")


def test_imported_sequences_preserve_source_fields_and_block_collision(tmp_path):
    source = tmp_path/"input.csv"
    source.write_text("Name\nAlice\nBob\n", encoding="utf-8")
    store = import_records(DataConfig(path=str(source)), tmp_path/"input.db")
    template = Template(sequences=[SequenceSpec(name="Seq")])
    records = CompositionRecords(template, store)
    original = records.record(2)
    assert sequence_record(template, original, 2) == {"Name": "Bob", "Seq": "000002"}
    assert original == {"Name": "Bob"}
    template.sequences[0].name = "Name"
    with pytest.raises(CompositionError, match="conflict"):
        CompositionRecords(template, store)
    with pytest.raises(CompositionError, match="conflict"):
        render_preview(template, {"Name": "Bob"})
    result = generate(ProductionJob(template.to_dict(), str(store.path), str(tmp_path/"out")))
    assert result.status == "failed" and result.generated_files == 0
    assert "conflict" in result.error


def test_preview_random_access_and_chunked_output_share_exact_values(tmp_path):
    template = model(4)
    record4 = dispatch({"task": "preview", "template": template.to_dict(), "design": False,
                        "record": 4, "page": 1, "target": str(tmp_path/"preview.pdf")})
    with fitz.open(record4["pdf"]) as doc:
        preview_text = doc[0].get_text().strip()
        preview_pixels = doc[0].get_pixmap().samples
    assert preview_text == "INV-00106-HK / 008"
    job = ProductionJob(template.to_dict(), "", str(tmp_path/"out"), chunk_size=3)
    result = generate(job)
    assert result.status == "completed", result.error
    assert result.input_records == result.successful_records == 4
    assert result.generated_pages == 8
    with fitz.open(result.output_pdf) as doc:
        assert doc[0].get_text().strip() == "INV-00100-HK / 001"
        assert doc[1].get_text().strip() == "INV-00100-HK / 002"
        assert doc[2].get_text().strip() == "INV-00102-HK / 003"
        assert doc[7].get_pixmap().samples == preview_pixels
    rerun = generate(ProductionJob(template.to_dict(), "", str(tmp_path/"out"), chunk_size=2))
    assert rerun.status == "completed"
    with fitz.open(result.output_pdf) as a, fitz.open(rerun.output_pdf) as b:
        assert [p.get_text() for p in a] == [p.get_text() for p in b]
    log = json.loads((tmp_path/"out"/job.job_id/"job.json").read_text(encoding="utf-8"))
    assert log["record_mode"] == "generated"
    assert log["sequences"][1]["first"] == "001" and log["sequences"][1]["last"] == "008"
    assert "generated record ordinal" in log["record_identity"]


@pytest.mark.parametrize("pages", [1, 2, 3])
@pytest.mark.parametrize("duplex", [False, True])
def test_no_media_page_sequences_follow_output_pages_and_preview(tmp_path, pages, duplex):
    template = model(3)
    template.pages = [PageSpec(id=f"page-{i}", elements=[
        Element(value="{{Ticket}} / {{PageSeq}}", width_mm=150)]) for i in range(pages)]
    template.media = {"enabled": False, "duplex": duplex}
    assert all(not element.barcode_profile for element in template.all_elements())
    physical_count = pages + int(duplex and pages % 2)
    expected = []
    for ordinal in range(1, 4):
        expected.extend(f"INV-{100 + (ordinal - 1) * 2:05d}-HK / "
                        f"{(ordinal - 1) * physical_count + page + 1:03d}" for page in range(pages))
        if physical_count > pages:
            expected.append("")
    job = ProductionJob(template.to_dict(), "", str(tmp_path / "out"), chunk_size=2)
    result = generate(job)
    assert result.status == "completed", result.error
    assert result.generated_pages == 3 * physical_count
    with fitz.open(result.output_pdf) as pdf:
        assert [page.get_text().strip() for page in pdf] == expected
        for ordinal in (2, 3):
            for page_index in (0, pages - 1):
                preview = dispatch({"task": "preview", "template": template.to_dict(),
                                    "design": False, "record": ordinal, "page": page_index,
                                    "target": str(tmp_path / f"preview-{ordinal}-{page_index}.pdf")})
                output_index = (ordinal - 1) * physical_count + page_index
                with fitz.open(preview["pdf"]) as current:
                    assert current.page_count == 1
                    assert current[0].get_text().strip() == expected[output_index]
                    assert current[0].get_pixmap().samples == pdf[output_index].get_pixmap().samples
    log = json.loads((tmp_path / "out" / job.job_id / "job.json").read_text(encoding="utf-8"))
    by_name = {sequence["name"]: sequence for sequence in log["sequences"]}
    assert by_name["PageSeq"]["first"] == "001"
    assert by_name["PageSeq"]["last"] == f"{2 * physical_count + pages:03d}"
    assert by_name["Ticket"]["first"] == "INV-00100-HK"
    assert by_name["Ticket"]["last"] == "INV-00104-HK"


def test_page_sequence_cache_tracks_duplex_changes_without_media():
    template = model(3)
    template.pages.append(PageSpec(id="third"))
    for duplex, expected in ((False, "004"), (True, "005"), (False, "004"), (True, "005")):
        template.media = {"enabled": False, "duplex": duplex}
        assert sequence_record(template, {}, 2, 0)["PageSeq"] == expected
        assert sequence_record(template, {}, 2, 2)["Ticket"] == "INV-00102-HK"
    template.pages.append(PageSpec(id="fourth"))
    assert sequence_record(template, {}, 2, 3)["PageSeq"] == "008"
    template.pages.append(PageSpec(id="fifth"))
    assert sequence_record(template, {}, 2, 0)["PageSeq"] == "007"


def test_page_sequence_cache_tracks_media_blank_insertion_and_disabled_media():
    from tests.composition.test_media_duplex_sheets import four_page_template
    template = four_page_template()
    template.sequences = [SequenceSpec("PageSeq", 1, 1, 3, scope="page")]
    assert sequence_record(template, {}, 2, 2)["PageSeq"] == "007"
    template.media["assignments"].update({"2": "LH_B", "3": "LH_A"})
    template.media["blank_policy"] = "insert"
    assert sequence_record(template, {}, 2, 2)["PageSeq"] == "013"
    template.media["enabled"] = False
    assert sequence_record(template, {}, 2, 2)["PageSeq"] == "007"
    template.media["enabled"] = True
    assert sequence_record(template, {}, 2, 2)["PageSeq"] == "013"


def test_duplex_page_sequence_formatting_and_rule_values_without_media(tmp_path):
    template = model(3)
    template.pages.append(PageSpec(id="third"))
    template.media = {"enabled": False, "duplex": True}
    template.sequences[1] = SequenceSpec("PageSeq", 9, 3, 4, "P-", "-END", scope="page")
    assert sequence_record(template, {}, 3, 2)["PageSeq"] == "P-0039-END"
    template.sequences[1] = SequenceSpec("PageSeq", 1, 1, 3, scope="page")
    template.pages[0].elements.append(Element(value="VISIBLE", y_mm=50, rules=ElementRules(
        ConditionGroup("all", [RuleCondition("PageSeq", "gt", "number", "4")]))))
    result = generate(ProductionJob(template.to_dict(), "", str(tmp_path / "out")))
    assert result.status == "completed", result.error
    assert result.rule_summary["hidden_occurrences"] == 1
    with fitz.open(result.output_pdf) as pdf:
        assert "VISIBLE" not in pdf[0].get_text()
        assert "VISIBLE" in pdf[4].get_text()  # Second record starts at output page 5.


def test_sequence_rules_use_correct_page_in_preflight_and_preview(tmp_path):
    template = model()
    template.pages[0].elements.append(Element(
        value="VISIBLE", y_mm=50,
        rules=ElementRules(ConditionGroup("all", [RuleCondition("PageSeq", "gt", "number", "4")]))))
    result = generate(ProductionJob(template.to_dict(), "", str(tmp_path/"out")))
    assert result.status == "completed", result.error
    assert result.rule_summary["hidden_occurrences"] == 2
    assert result.rule_summary["complete"]
    with fitz.open(result.output_pdf) as pdf:
        assert "VISIBLE" not in pdf[2].get_text()
        assert "VISIBLE" in pdf[4].get_text()
    response = dispatch({"task": "preview", "template": template.to_dict(), "record": 3, "page": 0,
                         "design": False, "target": str(tmp_path/"preview.pdf")})
    assert response["rules"][0]["visible"]


def test_cancel_does_not_consume_numbers_or_publish_pdf(tmp_path):
    template = model(100)
    ticks = 0
    def cancelled():
        nonlocal ticks
        ticks += 1
        return ticks > 5
    result = generate(ProductionJob(template.to_dict(), "", str(tmp_path/"out")), is_cancelled=cancelled)
    assert result.status == "cancelled" and result.generated_files == 0 and not result.output_pdf
    assert sequence_record(template, {}, 1)["Ticket"] == "INV-00100-HK"
    assert not list((tmp_path/"out").rglob("production.pdf"))


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_dialog_controls_examples_conflicts_and_validation(app):
    dialog = SequenceDialog(model(), ["Name"], 398)
    dialog.table.setCurrentCell(0, 0)
    assert "INV-00100-HK" in dialog.example.text()
    dialog.mode.setCurrentIndex(1)
    dialog.quantity.setValue(398)
    dialog.table.setCurrentCell(1, 0)
    assert "796" in dialog.example.text()
    dialog.table.item(1, 0).setText("Ticket")
    assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    dialog.table.item(1, 0).setText("PageSeq")
    dialog.table.item(0, 2).setText("0")
    assert "increment cannot be zero" in dialog.error.text()
    dialog.table.item(0, 2).setText("2")
    dialog.accept()
    assert dialog.choice.generated_count == 398 and dialog.choice.record_mode == "generated"
    dialog.deleteLater()


def test_gui_generated_fields_preview_production_undo_and_reopen(app, tmp_path):
    w = CompositionWindow()
    try:
        w.show()
        seq = SequenceSpec("Ticket", 1, 1, 4, "T-", "")
        assert w.apply_sequences([seq], "generated", 3)
        assert w.record_count == 3 and w.fields.item(0).text() == "Ticket"
        assert "no data file required" in w.data_summary.text()
        w.undo.undo()
        assert w.record_count == 0 and not w.template.sequences
        w.undo.redo()
        assert w.record_count == 3
        w.add_field("Ticket", 25, 30)
        # Real preview process; no CSV/snapshot.
        w.tabs.setCurrentIndex(2)
        w.record.setValue(3)
        wait(lambda: "Record 3" in w.preview_state.text() and not w.workers)
        assert not w.last_output
        saved = save_project(w.template, tmp_path/"project.pdcx")
        assert load_project(saved).sequences == [seq]
        w.start_production(str(tmp_path/"out"))
        from tests.composition.review_helpers import confirm_review
        confirm_review(w)
        wait(lambda: not w.production_worker and bool(w.last_output))
        with fitz.open(w.last_output) as pdf:
            assert [p.get_text().strip() for p in pdf] == ["T-0001", "T-0002", "T-0003"]
        w.undo.setClean()
        w.open_project(path=str(saved))
        assert w.record_count == 3 and w.import_worker is None
        assert not w.apply_sequences([], "generated", 3)
        assert "still used" in w.message.text()
    finally:
        cleanup(w)


def test_gui_imported_mode_switch_and_original_field_collision(app, tmp_path):
    w = CompositionWindow()
    try:
        source = tmp_path/"data.csv"
        source.write_text("Account\nA\nB\n", encoding="utf-8")
        config = DataConfig(path=str(source))
        store = import_records(config, w.directory/"test.db")
        w._import_ready({"store": str(store.path), "metadata": store.metadata,
                         "sample": [store.record(1), store.record(2)]}, config)
        assert not w.apply_sequences([SequenceSpec("Account")], "imported", 2)
        assert w.fields.item(0).text() == "Account"
        assert w.apply_sequences([SequenceSpec("Seq")], "imported", 2)
        assert w._store()["sample"][1] == {"Account": "B", "Seq": "000002"}
        assert w.apply_sequences([SequenceSpec("Seq")], "generated", 10)
        assert w.record_count == 10 and w._store()["metadata"]["fields"] == ["Seq"]
        assert w.apply_sequences([SequenceSpec("Seq")], "imported", 10)
        assert w.record_count == 2 and w._store()["sample"][0]["Account"] == "A"
    finally:
        cleanup(w)
