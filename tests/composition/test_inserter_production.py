import csv
from pathlib import Path

import fitz
import pytest

from composition.engine.barcode_profiles import BarcodeProfile
from composition.overlay.generator import generate as generate_overlay
from composition.overlay.model import EnvelopeSpec, OverlayJob, OverlayObject
from composition.pdf_source.model import EnvelopeSettings
from composition.pdf_source.source import inspect_source
from composition.production.generator import generate
from composition.production.model import ProductionJob
from composition.template.model import Element, PageSpec, SequenceSpec, Template
from tests.composition.test_pdf_overlay_models import make_source


def template_for(pages=4, count=2, duplex=True):
    profile = BarcodeProfile.inserter().to_dict()
    return Template(pages=[PageSpec(id=f"page_{i}", elements=[Element(type="i25", width_mm=100, height_mm=14,
        barcode_profile=profile)]) for i in range(pages)], record_mode="generated", generated_count=count,
        media={"duplex": duplex})


@pytest.mark.parametrize("pages,total,marks", [(4, 8, 4), (3, 8, 4), (1, 4, 2)])
def test_template_duplex_decode_reconcile_and_audit(tmp_path, pages, total, marks):
    template = template_for(pages)
    result = generate(ProductionJob(template.to_dict(), "", str(tmp_path), chunk_size=3))
    assert result.status == "completed", result.error
    assert result.generated_pages == total
    assert result.expected_barcodes == result.rendered_barcodes == result.decoded_barcodes == marks
    with Path(result.report_dir, "barcodes.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == marks and all(len(row["Payload"]) == 18 for row in rows)
    assert rows[0]["Output page"] == "1"
    assert rows[0]["EOG"] == ("1" if pages == 1 else "0")
    with fitz.open(result.output_pdf) as document:
        assert not document[1].get_drawings()


def test_template_preflight_missing_duplicate_size_and_data(tmp_path):
    for case in ("missing", "duplicate", "width", "data"):
        template = template_for()
        if case == "missing":
            template.pages[2].elements.clear()
        elif case == "duplicate":
            template.pages[0].elements.append(Element(type="i25", y_mm=50, width_mm=100,
                barcode_profile=BarcodeProfile.inserter().to_dict()))
        elif case == "width":
            template.pages[0].elements[0].width_mm = 20
        else:
            for element in template.all_elements():
                element.barcode_profile["customer_field"] = "MissingCustomer"
        result = generate(ProductionJob(template.to_dict(), "", str(tmp_path/case)))
        assert result.status == "failed" and not result.output_pdf
        assert result.generated_pages == 0 and result.error_record == 1
        assert "Barcode preflight" in result.error


def test_overlay_preset_uses_exact_physical_sheet_codes(tmp_path):
    path = make_source(tmp_path/"source.pdf", 8)
    settings = EnvelopeSettings(pages_per_envelope=4, duplex=True)
    barcode = OverlayObject(Element(type="i25", width_mm=100, height_mm=14), scope="front", control=True,
                            profile=BarcodeProfile.inserter())
    spec = EnvelopeSpec(inspect_source(path, settings), settings, [barcode], required_scope="front")
    result = generate_overlay(OverlayJob(spec.to_dict(), str(tmp_path/"output")))
    assert result.status == "completed", result.error
    assert result.expected_barcodes == result.decoded_barcodes == 4
    with Path(result.report_dir, "barcodes.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["Payload"] == "000000000000000000"
    assert rows[1]["Payload"] == "000100100000000006"
    assert [row["Sheet"] for row in rows] == ["1", "2", "1", "2"]
    assert [row["Sheet sequence"] for row in rows] == ["00", "01", "02", "03"]


def test_1000_envelopes_real_decode_and_rollover(tmp_path):
    template = template_for(pages=1, count=1000, duplex=False)
    result = generate(ProductionJob(template.to_dict(), "", str(tmp_path), chunk_size=73))
    assert result.status == "completed", result.error
    assert result.generated_pages == result.decoded_barcodes == result.expected_barcodes == 1000
    with Path(result.report_dir, "barcodes.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["Group sequence"] for row in rows[97:101]] == ["97", "98", "99", "00"]
    assert rows[-1]["Envelope"] == "1000" and rows[-1]["Group sequence"] == "99"
    assert [row["Sheet sequence"] for row in rows] == [f"{i % 100:02d}" for i in range(1000)]
    assert [int(row["Job sheet"]) for row in rows] == list(range(1, 1001))


def test_media_inserted_backs_share_the_same_barcode_sheet_plan(tmp_path):
    from tests.composition.test_media_duplex_sheets import four_page_template
    model = four_page_template()
    model.media["assignments"].update({"2": "LH_B", "3": "LH_A"})
    model.media["blank_policy"] = "insert"
    model.generated_count = 1
    for page in model.pages:
        page.elements.append(Element(type="i25", y_mm=50, width_mm=100, height_mm=14,
                                     barcode_profile=BarcodeProfile.inserter().to_dict()))
    result = generate(ProductionJob(model.to_dict(), "", str(tmp_path)))
    assert result.status == "completed", result.error
    assert result.generated_pages == 8 and result.decoded_barcodes == 4
    with Path(result.report_dir, "barcodes.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [r["Output page"] for r in rows] == ["1", "3", "5", "7"]
    assert [r["Sheet"] for r in rows] == ["1", "2", "3", "4"]
    assert [r["EOG"] for r in rows] == ["0", "0", "0", "1"]


def test_variable_envelope_sizes_and_odd_blank_backs(tmp_path):
    from tests.composition.test_mailpiece_detection import variable_spec
    spec = variable_spec(tmp_path, lengths=(1, 3, 5), duplex=True)
    spec.objects = [OverlayObject(Element(type="i25", width_mm=100, height_mm=14), scope="front", control=True,
                                 profile=BarcodeProfile.inserter())]
    spec.required_scope = "front"
    result = generate_overlay(OverlayJob(spec.to_dict(), str(tmp_path/"output")))
    assert result.status == "completed", result.error
    assert result.generated_pages == 12 and result.decoded_barcodes == 6
    with Path(result.report_dir, "barcodes.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [r["Envelope"] for r in rows] == ["1", "2", "2", "3", "3", "3"]
    assert [r["EOG"] for r in rows] == ["1", "0", "1", "0", "0", "1"]
    assert [r["Sheet sequence"] for r in rows] == ["00", "01", "02", "03", "04", "05"]
    assert [r["Job sheet"] for r in rows] == ["1", "2", "3", "4", "5", "6"]


def test_workflow_reuses_profile_and_physical_counts_without_media(tmp_path):
    from composition.template.serializer import save_project
    from workflow.batch import BatchJob, BatchRun, approve, execute_batch, prepare
    from workflow.model import WorkflowSpec
    model = template_for(pages=3)
    model.record_mode = "imported"
    path = save_project(model, tmp_path/"template.pdcx")
    data = tmp_path/"data.csv"
    data.write_text("Name\nOne\nTwo\n", encoding="utf-8")
    job = BatchJob(template_path=str(path), data_path=str(data), output_name="letters.pdf")
    spec = WorkflowSpec.mail_merge()
    run = prepare(spec, BatchRun(jobs=[job]), tmp_path/"scratch")
    assert job.status == "Needs review", job.error
    assert job.pages_per_record == 4 and job.expected_pages == 8
    approve(run, [job.id])
    execute_batch(spec, run, tmp_path/"production")
    assert job.status == "Completed", job.error
    assert job.result["generated_pages"] == 8 and job.result["decoded_barcodes"] == 4


def test_system_count_and_page_sequence_follow_duplex_blanks():
    from composition.data.sequences import open_records, sequence_record
    from composition.engine.barcode_profiles import profile_values
    model = template_for(pages=3, count=27)
    model.sequences = [SequenceSpec(name="PageSeq", scope="page", padding=0)]
    records = open_records(model)
    value = sequence_record(model, records.record(2), 2, 0)
    assert value["PageSeq"] == "5"
    assert profile_values(value)["EnvelopeCount"] == "27"
    assert profile_values(value)["OutputPage"] == "5"


def test_imported_200_single_page_records_have_continuous_sheet_sequence(tmp_path):
    from composition.data.source import import_records
    from composition.template.model import DataConfig
    data = tmp_path / "data.csv"
    data.write_text("Customer\n" + "\n".join(f"Customer {i}" for i in range(200)), encoding="utf-8")
    store = import_records(DataConfig(path=str(data)), tmp_path / "records.db")
    model = template_for(pages=1, duplex=False)
    model.record_mode = "imported"
    result = generate(ProductionJob(model.to_dict(), str(store.path), str(tmp_path / "output"), chunk_size=37))
    assert result.status == "completed", result.error
    assert result.sheets == result.generated_pages == result.decoded_barcodes == 200
    with Path(result.report_dir, "barcodes.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [r["Sheet sequence"] for r in rows] == [f"{i % 100:02d}" for i in range(200)]
    assert [r["Group sequence"] for r in rows] == [r["Sheet sequence"] for r in rows]
    assert all(r["EOG"] == "1" for r in rows)


@pytest.mark.parametrize("duplex", [False, True])
def test_two_page_template_only_front_barcode_uses_explicit_printing(tmp_path, duplex):
    model = template_for(pages=2, duplex=duplex)
    model.pages[1].elements.clear()
    result = generate(ProductionJob(model.to_dict(), "", str(tmp_path)))
    if duplex:
        assert result.status == "completed", result.error
        assert result.printing == "duplex" and result.sheets == result.decoded_barcodes == 2
        assert result.generated_pages == 4 and result.inserted_blanks == 0
    else:
        assert result.status == "failed" and result.generated_pages == 0
        assert "Simplex: template page 2" in result.error and "choose Duplex" in result.error


def test_legacy_inserter_cannot_silently_generate(tmp_path):
    model = template_for(pages=1, duplex=False)
    profile = model.elements[0].barcode_profile
    profile.update(version=2, sheet_sequence_scope="envelope")
    result = generate(ProductionJob(model.to_dict(), "", str(tmp_path)))
    assert result.status == "failed" and result.generated_pages == 0
    assert "confirm Update I25" in result.error


def test_media_job_sheet_sequence_counts_inserted_backs_once_across_records(tmp_path):
    from tests.composition.test_media_duplex_sheets import four_page_template
    model = four_page_template()
    model.media["assignments"].update({"2": "LH_B", "3": "LH_A"})
    model.media["blank_policy"] = "insert"
    model.generated_count = 2
    for page in model.pages:
        page.elements.append(Element(type="i25", y_mm=50, width_mm=100, height_mm=14,
                                     barcode_profile=BarcodeProfile.inserter().to_dict()))
    result = generate(ProductionJob(model.to_dict(), "", str(tmp_path)))
    assert result.status == "completed", result.error
    assert result.sheets == result.decoded_barcodes == 8 and result.generated_pages == 16
    with Path(result.report_dir, "barcodes.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [r["Sheet sequence"] for r in rows] == [f"{i:02d}" for i in range(8)]
    assert [r["Group sequence"] for r in rows] == ["00"]*4 + ["01"]*4
    assert [r["EOG"] for r in rows] == ["0", "0", "0", "1"]*2


def test_workflow_jobs_reset_independently_and_legacy_blocks_review(tmp_path):
    from composition.template.serializer import save_project
    from workflow.batch import BatchJob, BatchRun, approve, execute_batch, prepare
    from workflow.model import WorkflowSpec
    model = template_for(pages=2)
    model.pages[1].elements.clear()
    model.record_mode = "imported"
    path = save_project(model, tmp_path / "current.pdcx")
    legacy = Template.from_dict(model.to_dict())
    legacy.elements[0].barcode_profile.update(version=2, sheet_sequence_scope="envelope")
    old_path = save_project(legacy, tmp_path / "old.pdcx")
    data = tmp_path / "data.csv"
    data.write_text("Name\nOne\nTwo\n", encoding="utf-8")
    jobs = [BatchJob(template_path=str(path), data_path=str(data), output_name=f"job{i}.pdf") for i in range(2)]
    old = BatchJob(template_path=str(old_path), data_path=str(data), output_name="old.pdf")
    spec = WorkflowSpec.mail_merge()
    run = prepare(spec, BatchRun(jobs=[*jobs, old]), tmp_path / "scratch")
    assert old.status == "Blocked" and "confirm Update I25" in old.error and not old.approved
    assert all(job.status == "Needs review" for job in jobs)
    run.jobs = jobs
    approve(run, [job.id for job in jobs])
    execute_batch(spec, run, tmp_path / "output")
    for job in jobs:
        assert job.status == "Completed", job.error
        with Path(job.result["report_dir"], "barcodes.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert [r["Sheet sequence"] for r in rows] == ["00", "01"]
        assert [r["Group sequence"] for r in rows] == ["00", "01"]


def test_plain_odd_duplex_uses_same_plan_without_barcodes(tmp_path):
    model = Template(pages=[PageSpec(id=f"p{i}") for i in range(3)],
                     record_mode="generated", generated_count=2, media={"duplex": True})
    result = generate(ProductionJob(model.to_dict(), "", str(tmp_path)))
    assert result.status == "completed", result.error
    assert result.generated_pages == 8 and result.sheets == 4 and result.inserted_blanks == 2
