"""Fixed layouts through actual PDFs, full preflight, cycles and shared clients."""
import csv
from pathlib import Path

import pytest

from composition.data.source import import_records
from composition.engine.barcode_profiles import BarcodeProfile
from composition.engine.generic_layout import BarcodeSegment
from composition.overlay.generator import generate as generate_overlay
from composition.overlay.model import EnvelopeSpec, OverlayJob, OverlayObject
from composition.pdf_source.model import EnvelopeSettings
from composition.pdf_source.source import inspect_source
from composition.production.generator import generate
from composition.production.model import ProductionJob
from composition.template.model import DataConfig, Element, PageSpec, SequenceSpec, Template
from composition.template.serializer import load_project, save_project
from tests.composition.test_pdf_overlay_models import make_source


def counter_profile(cycle=False, scope="record"):
    return BarcodeProfile.fixed_layout(4, [BarcodeSegment(name="Counter", length=2, source="sequence", format="numeric",
        overflow="cycle" if cycle else "stop", scope=scope), BarcodeSegment(name="Fixed", length=2, value="00")])


def model(count=2, pages=1, cycle=False, duplex=False):
    return Template(record_mode="generated", generated_count=count, media={"duplex": duplex},
        pages=[PageSpec(elements=[Element(type="i25", width_mm=90, height_mm=14,
            barcode_profile=counter_profile(cycle).to_dict())]) for _ in range(pages)])


def rows(result, name):
    with Path(result.report_dir, name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_1000_records_real_decode_and_cycle_report(tmp_path):
    result = generate(ProductionJob(model(1000, cycle=True).to_dict(), "", str(tmp_path), chunk_size=73))
    assert result.status == "completed", result.error
    assert result.generated_pages == result.expected_barcodes == result.rendered_barcodes == result.decoded_barcodes == 1000
    barcodes = rows(result, "barcodes.csv")
    assert [r["Payload"] for r in barcodes[98:102]] == ["9800", "9900", "0000", "0100"]
    cycles = rows(result, "barcode-cycles.csv")
    assert len(cycles) == 900
    assert cycles[0]["Record ordinal"] == cycles[0]["Envelope"] == cycles[0]["Output page"] == "101"
    assert cycles[0]["Raw sequence"] == "100" and cycles[0]["Encoded sequence"] == "00"
    assert cycles[-1]["Raw sequence"] == "999" and cycles[-1]["Encoded sequence"] == "99"


def test_overflow_blocks_before_composition(tmp_path):
    result = generate(ProductionJob(model(101).to_dict(), "", str(tmp_path)))
    assert result.status == "failed" and result.error_record == 101
    assert result.generated_pages == result.generated_files == result.processed_records == 0
    assert not result.output_pdf and not list(Path(result.report_dir).glob("*.pdf"))
    assert "Counter" in result.error and "needs 3 digits" in result.error and "output page 101" in result.error


@pytest.mark.parametrize("bad", ["00001", "１２３４", "", "-001"])
def test_all_imported_values_checked_without_truncation(tmp_path, bad):
    source = tmp_path / "data.csv"
    source.write_text('Account\n0001\n"'+bad+'"\n', encoding="utf-8")
    store = import_records(DataConfig(path=str(source)), tmp_path / "data.sqlite")
    p = BarcodeProfile.fixed_layout(4, [BarcodeSegment(name="Customer ID", length=4, source="data", value="Account")])
    template = model()
    template.record_mode = "imported"
    template.elements[0].barcode_profile = p.to_dict()
    result = generate(ProductionJob(template.to_dict(), str(store.path), str(tmp_path / "output")))
    assert result.status == "failed" and result.error_record == 2 and result.generated_pages == 0
    assert "Customer ID" in result.error or "I25" in result.error


def test_data_system_collision_and_existing_sequence_actual_pdf(tmp_path):
    source = tmp_path / "data.csv"
    source.write_text("EnvelopeSeq\nAB\nCD\n", encoding="utf-8")
    store = import_records(DataConfig(path=str(source)), tmp_path / "data.sqlite")
    p = BarcodeProfile.fixed_layout(6, [BarcodeSegment(name="Imported", length=2, source="data", value="EnvelopeSeq"),
        BarcodeSegment(name="Envelope", length=2, source="system", value="EnvelopeSeq", format="numeric"),
        BarcodeSegment(name="Existing", length=2, source="sequence", value="Reference", format="numeric")])
    template = model()
    template.record_mode = "imported"
    template.sequences = [SequenceSpec(name="Reference", start=7)]
    template.elements[0].type = "code128"
    template.elements[0].barcode_profile = p.to_dict()
    result = generate(ProductionJob(template.to_dict(), str(store.path), str(tmp_path / "out")))
    assert result.status == "completed", result.error
    assert [r["Payload"] for r in rows(result, "barcodes.csv")] == ["AB0107", "CD0208"]


def test_duplex_sheet_scope_page_scope_and_blank_backs(tmp_path):
    template = model(pages=3, duplex=True)
    p = BarcodeProfile.fixed_layout(4, [BarcodeSegment(name="Sheet", length=2, source="sequence", scope="sheet", format="numeric"),
        BarcodeSegment(name="Output page", length=2, source="sequence", scope="page", format="numeric")])
    for element in template.all_elements():
        element.barcode_profile = p.to_dict()
    result = generate(ProductionJob(template.to_dict(), "", str(tmp_path)))
    assert result.status == "completed", result.error
    assert result.generated_pages == 8 and result.decoded_barcodes == 6
    assert [r["Payload"] for r in rows(result, "barcodes.csv")] == ["0000", "0001", "0102", "0004", "0005", "0106"]
    assert [r["Output page"] for r in rows(result, "barcodes.csv")] == ["1", "2", "3", "5", "6", "7"]


def test_cancel_preflight_retains_diagnostics_only(tmp_path):
    cancel = False
    def progress(done, total, message):
        nonlocal cancel
        if "Generic" in message:
            cancel = True
    result = generate(ProductionJob(model(1000, cycle=True).to_dict(), "", str(tmp_path)),
                      progress=progress, is_cancelled=lambda: cancel)
    assert result.status == "cancelled" and not result.output_pdf and result.generated_pages == 0
    assert not list(Path(result.report_dir).glob("*.pdf"))


def test_overlay_variable_envelopes_share_scope_and_cycle_report(tmp_path):
    from tests.composition.test_mailpiece_detection import variable_spec
    spec = variable_spec(tmp_path, lengths=(1, 3, 5), duplex=True)
    profile = counter_profile(cycle=True, scope="sheet")
    profile.segments[0].start = 100
    spec.objects = [OverlayObject(Element(type="i25", width_mm=90, height_mm=14), scope="front", control=True, profile=profile)]
    spec.required_scope = "front"
    result = generate_overlay(OverlayJob(spec.to_dict(), str(tmp_path / "out")))
    assert result.status == "completed", result.error
    assert result.generated_pages == 12 and result.decoded_barcodes == 6
    assert [r["Payload"] for r in rows(result, "barcodes.csv")] == ["0000", "0000", "0100", "0000", "0100", "0200"]
    assert [r["Envelope"] for r in rows(result, "barcode-cycles.csv")] == ["1", "2", "2", "3", "3", "3"]


def test_overlay_data_context_and_hidden_invalid_barcode(tmp_path):
    from composition.template.model import ConditionGroup, ElementRules, RuleCondition
    source = make_source(tmp_path / "source.pdf", 2)
    settings = EnvelopeSettings(pages_per_envelope=1)
    profile = BarcodeProfile.fixed_layout(4, [BarcodeSegment(name="Customer", length=4, source="data", value="Account")])
    element = Element(type="i25", width_mm=90, height_mm=14,
        rules=ElementRules(visible_when=ConditionGroup(conditions=[RuleCondition(field="Account", operator="ne", value="bad")])) )
    spec = EnvelopeSpec(inspect_source(source, settings), settings, [OverlayObject(element, profile=profile)], external_fields=["Account"])
    result = generate_overlay(OverlayJob(spec.to_dict(), str(tmp_path / "out")),
                              external_values=lambda page: {"Account": "0001" if page.envelope == 1 else "bad"})
    assert result.status == "completed", result.error
    assert result.decoded_barcodes == 1 and rows(result, "barcodes.csv")[0]["Payload"] == "0001"


def test_project_migrations_keep_fixed_profiles_and_legacy_payload(tmp_path):
    template = model()
    path = save_project(template, tmp_path / "template.pdcx")
    restored = load_project(path)
    assert restored.template_version == 12
    assert restored.elements[0].barcode_profile == template.elements[0].barcode_profile
    raw = template.to_dict()
    raw["template_version"] = 11
    with pytest.raises(ValueError, match="version 12"):
        Template.from_dict(raw)
    source = make_source(tmp_path / "source.pdf", 2)
    cfg = EnvelopeSettings(pages_per_envelope=1)
    overlay = EnvelopeSpec(inspect_source(source, cfg), cfg, [OverlayObject(Element(type="i25", width_mm=90), profile=counter_profile())])
    reopened = EnvelopeSpec.from_dict(overlay.to_dict())
    assert reopened.overlay_version == 8 and reopened.objects[0].profile.to_dict() == overlay.objects[0].profile.to_dict()
    raw = overlay.to_dict()
    raw["overlay_version"] = 7
    with pytest.raises(ValueError, match="version 8"):
        EnvelopeSpec.from_dict(raw)


@pytest.mark.parametrize("symbology,value", [("i25", "01"), ("i25", "0001"), ("code128", "AB01"), ("qr", "田001")])
def test_supported_formats_really_decode_without_extra_checksum(tmp_path, symbology, value):
    p = BarcodeProfile.fixed_layout(len(value), [BarcodeSegment(name="Exact", length=len(value), value=value)])
    template = model(count=1)
    element = template.elements[0]
    element.type, element.width_mm, element.height_mm = symbology, 60, 35 if symbology == "qr" else 14
    element.barcode_profile = p.to_dict()
    result = generate(ProductionJob(template.to_dict(), "", str(tmp_path)))
    assert result.status == "completed", result.error
    assert rows(result, "barcodes.csv")[0]["Payload"] == value and result.decoded_barcodes == 1


def test_workflow_inspection_materialized_sequence_and_preview(tmp_path):
    from tests.test_mail_merge_workflow import pair, recipe
    from workflow.inspection import inspect_step, inspection_preview
    job = pair(tmp_path, records=4)
    template = load_project(job.template_path)
    p = BarcodeProfile.fixed_layout(4, [BarcodeSegment(name="Existing", length=2, source="sequence", value="Seq",
        format="numeric", overflow="cycle"), BarcodeSegment(name="Fixed", length=2, value="00")])
    for page in template.pages:
        page.elements.append(Element(type="i25", y_mm=60, width_mm=90, height_mm=14, barcode_profile=p.to_dict()))
    save_project(template, job.template_path)
    spec = recipe([job]).upgraded()
    target = spec.node("compose").id
    checked = inspect_step(spec, target, tmp_path / "checks", job=job)["result"]
    assert checked["status"] == "Checked", checked["error"]
    assert checked["materialized_sequences"] == ["Seq"]
    preview = inspection_preview(tmp_path / "checks", checked["run_id"], target, spec,
        tmp_path / "checks" / "preview.png", job=job, record=4, page=2)
    assert Path(preview["image"]).exists() and not job.approved
    assert load_project(job.template_path).elements[-1].barcode_profile == p.to_dict()


def test_workflow_all_record_check_blocks_unapproved_job(tmp_path):
    from workflow.batch import BatchJob, BatchRun, prepare
    from workflow.model import WorkflowSpec
    template = model(101)
    path = save_project(template, tmp_path / "template.pdcx")
    job = BatchJob(template_path=str(path))
    prepare(WorkflowSpec.mail_merge(), BatchRun(jobs=[job]), tmp_path / "checks")
    assert job.status == "Blocked" and not job.approved
    assert "Record 101" in job.error and "Counter" in job.error


def test_workflow_data_segment_issue_keeps_field_identity(tmp_path):
    from tests.test_mail_merge_workflow import pair, recipe
    from workflow.inspection import inspect_step, inspection_rows
    job = pair(tmp_path)
    template = load_project(job.template_path)
    p = BarcodeProfile.fixed_layout(4, [BarcodeSegment(name="Customer", length=4, source="data", value="Name")])
    template.elements.append(Element(type="code128", width_mm=90, height_mm=14, y_mm=60, barcode_profile=p.to_dict()))
    save_project(template, job.template_path)
    spec = recipe([job]).upgraded()
    target = spec.node("compose").id
    checked = inspect_step(spec, target, tmp_path / "checks", job=job)["result"]
    assert checked["status"] == "Failed" and not job.approved
    issues = inspection_rows(tmp_path / "checks", checked["run_id"], checked["node_id"], spec, job=job, view="issues")
    assert issues["rows"][0]["field"] == "Name" and issues["rows"][0]["source_id"] == 2


def test_overlay_worker_preview_remains_json_serializable(tmp_path):
    import json

    from composition.worker import dispatch
    source = make_source(tmp_path / "source.pdf", 2)
    cfg = EnvelopeSettings(pages_per_envelope=1)
    spec = EnvelopeSpec(inspect_source(source, cfg), cfg,
        [OverlayObject(Element(type="i25", width_mm=90, height_mm=14), profile=counter_profile())])
    result = dispatch({"task": "overlay_preview", "project": spec.to_dict(), "envelope": 1, "print_page": 1,
                       "target": str(tmp_path / "preview.pdf"), "auto_repair": False})
    assert result["fields"]["EnvelopeIndex"] == "1"
    assert "__BarcodeContext" not in result["fields"]
    assert json.loads(json.dumps(result))["pdf"] == str(tmp_path / "preview.pdf")


def test_excel_text_field_preserves_source_zeros(tmp_path):
    from openpyxl import Workbook
    source = tmp_path / "data.xlsx"
    book = Workbook()
    book.active.append(["Account"])
    book.active.append(["0001"])
    book.active.append(["0002"])
    book.save(source)
    book.close()
    store = import_records(DataConfig(path=str(source), sheet="Sheet"), tmp_path / "data.sqlite")
    template = model()
    template.record_mode = "imported"
    template.elements[0].barcode_profile = BarcodeProfile.fixed_layout(4,
        [BarcodeSegment(name="Account", length=4, source="data", value="Account")]).to_dict()
    result = generate(ProductionJob(template.to_dict(), str(store.path), str(tmp_path / "out")))
    assert result.status == "completed", result.error
    assert [r["Payload"] for r in rows(result, "barcodes.csv")] == ["0001", "0002"]


def test_fixed_system_job_id_is_real_but_legacy_context_is_unchanged(tmp_path):
    from composition.data.sequences import sequence_record
    from composition.engine.barcode_profiles import profile_values
    from composition.engine.generic_layout import BarcodeContext
    template = model(count=1)
    template.elements[0].type = "code128"
    template.elements[0].barcode_profile = BarcodeProfile.fixed_layout(24,
        [BarcodeSegment(name="Job", length=24, source="system", value="JobId")]).to_dict()
    preview = sequence_record(template, {}, 1)
    assert BarcodeContext.from_values(preview).system["JobId"] == "00000000-000000-00000000"
    assert profile_values(preview)["JobId"] == "preview"
    identity = "20261007-010203-a1b2c3d4"
    result = generate(ProductionJob(template.to_dict(), "", str(tmp_path), job_id=identity))
    assert result.status == "completed", result.error
    assert rows(result, "barcodes.csv")[0]["Payload"] == identity


def test_cycle_audit_preserves_source_rows_after_sorting(tmp_path):
    from composition.data.sequences import open_records
    from composition.engine.generic_production import preflight
    from composition.media.planner import build_print_plan
    from workflow.transforms import snapshot, transform
    path = tmp_path / "input.sqlite"
    original = snapshot([(10, {"Name": "C"}), (20, {"Name": "A"}), (30, {"Name": "B"})], ["Name"], path)
    sorted_data = transform(original, tmp_path / "sorted.sqlite", "sort_records",
                            {"keys": [{"field": "Name", "type": "text", "descending": False}]}, node_id="sort")
    template = model(cycle=True)
    template.record_mode = "imported"
    template.elements[0].barcode_profile["segments"][0]["start"] = 100
    store = open_records(template, str(sorted_data.path))
    audit = tmp_path / "cycles.csv"
    assert preflight(template, store.records(), build_print_plan(template, store.count),
                     audit_path=audit, record_store=str(sorted_data.path)) == 3
    with audit.open(encoding="utf-8-sig", newline="") as stream:
        records = list(csv.DictReader(stream))
    assert [r["Record ordinal"] for r in records] == ["1", "2", "3"]
    assert [r["Source row"] for r in records] == ["20", "30", "10"]
