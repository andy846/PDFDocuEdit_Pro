"""Type-aware layouts must preserve the sole production plan and QC gates."""

import copy
import csv
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from composition.overlay.model import BarcodeProfile, BarcodeToken, EnvelopeSpec, OverlayJob, OverlayObject
from composition.overlay.renderer import page_values, render_preview
from composition.pdf_source.classification import accept_report
from composition.pdf_source.model import EnvelopeSettings
from composition.pdf_source.multi_detection import scan_pdf
from composition.pdf_source.planner import SYSTEM_FIELDS, EnvelopePlan
from composition.pdf_source.source import inspect_source
from composition.template.model import CompositionError, Element
from core.pdf_backend import fitz
from tests.composition.test_multi_rule_detection import profile
from tests.production_approval import expect_blocked, overlay_generate


def sample(tmp_path, *, duplex=True):
    path = tmp_path / "source.pdf"
    with fitz.open() as pdf:
        for text in ("Regular", "continued", "continued", "Reminder"):
            pdf.new_page().insert_text((40, 60), text)
        pdf.save(path)
    detection = scan_pdf(path, profile(), cache_path=tmp_path / "index.sqlite")["detection"]
    settings = EnvelopeSettings(groups=detection["groups"], duplex=duplex)
    spec = EnvelopeSpec(
        inspect_source(path, settings, uniform=True),
        settings,
        overlay_version=9,
        detection_review=accept_report(detection, tmp_path / "audit"),
        required_scope="front",
    )
    for template, x in (("REGULAR", 20), ("REMINDER", 100)):
        element = Element(type="qr", x_mm=x, y_mm=80, width_mm=30, height_mm=30)
        spec.objects.append(
            OverlayObject(
                element,
                scope="front",
                control=True,
                profile=BarcodeProfile(
                    tokens=[
                        BarcodeToken(value="TemplateID"),
                        BarcodeToken(value="EnvelopeSeq"),
                        BarcodeToken(value="JobSheetNo"),
                    ]
                ),
                template_ids=[template],
            )
        )
    spec.objects.append(
        OverlayObject(
            Element(
                value="{{TemplateID}} {{EnvelopeSeq}} {{LetterPage}}/{{LetterPageCount}}", x_mm=20, y_mm=120
            ),
            scope="all_source",
        )
    )
    return spec


def test_template_routing_keeps_global_numbering_and_blank_back_context(tmp_path):
    spec = sample(tmp_path)
    spec.validate()
    assert "TemplateID" not in SYSTEM_FIELDS
    plan = EnvelopePlan(spec.source.pages, spec.settings)
    values = [page_values(spec, p, "preview") for p in plan.pages()]
    assert [v["TemplateID"] for v in values] == ["REGULAR"] * 4 + ["REMINDER"] * 2
    assert [v["JobSheetNo"] for v in values] == ["1", "1", "2", "2", "3", "3"]
    assert values[3]["IsInsertedBlank"] == "1" and values[4]["EnvelopeIndex"] == "2"
    for envelope, expected in ((1, "REGULAR"), (2, "REMINDER")):
        raw, fields = render_preview(spec, envelope, 1)
        with fitz.open(stream=raw, filetype="pdf") as pdf:
            assert expected in pdf[0].get_text()
        assert fields["TemplateID"] == expected


def test_real_generation_type_specific_barcodes_and_traceable_reports(tmp_path):
    spec = sample(tmp_path)
    result = overlay_generate(OverlayJob(spec.to_dict(), str(tmp_path / "output")))
    assert result.status == "completed", result.error
    assert result.generated_pages == 6 and result.inserted_blanks == 2 and result.sheets == 3
    assert result.expected_barcodes == result.rendered_barcodes == result.decoded_barcodes == 3
    directory = Path(result.report_dir)
    with (directory / "classifications.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [r["TemplateID"] for r in rows] == ["REGULAR", "REMINDER"]
    assert [r["EnvelopeSeq"] for r in rows] == ["000001", "000002"]
    audit = json.loads((directory / "job.json").read_text(encoding="utf-8"))
    assert audit["mailpiece_classification"]["profile_id"] == spec.detection_review["profile_id"]
    assert not (directory / "source-snapshot.pdf").exists()
    with fitz.open(result.output_pdf) as pdf:
        assert "REGULAR" in pdf[0].get_text() and "REMINDER" in pdf[4].get_text()
        assert pdf[3].get_text() == pdf[5].get_text() == ""
    with (directory / "barcodes.csv").open(encoding="utf-8-sig", newline="") as stream:
        marks = list(csv.DictReader(stream))
    assert [r["Payload"] for r in marks] == ["REGULAR0000011", "REGULAR0000012", "REMINDER0000023"]


def test_missing_template_control_is_still_production_blocking(tmp_path):
    spec = sample(tmp_path)
    spec.objects = [o for o in spec.objects if o.template_ids != ["REMINDER"]]
    packet = expect_blocked(lambda: overlay_generate(OverlayJob(spec.to_dict(), str(tmp_path / "output"))))
    assert "exactly one" in str(packet)
    assert not list((tmp_path / "output").rglob("*.pdf"))


def test_unknown_scope_and_legacy_templateid_are_validated_separately(tmp_path):
    spec = sample(tmp_path)
    spec.objects[0].template_ids = ["UNKNOWN"]
    with pytest.raises(CompositionError):
        spec.validate()
    raw = spec.to_dict()
    raw["overlay_version"] = 8
    with pytest.raises(CompositionError):
        EnvelopeSpec.from_dict(raw)
    legacy = EnvelopeSpec(spec.source, EnvelopeSettings(pages_per_envelope=1), external_fields=["TemplateID"])
    legacy.objects = [OverlayObject(Element(value="{{TemplateID}}"))]
    legacy.validate()
    assert (
        page_values(
            legacy,
            EnvelopePlan(4, legacy.settings).page(1, 1),
            "preview",
            lambda p: {"TemplateID": "External"},
        )["TemplateID"]
        == "External"
    )


def test_production_profile_is_source_free_and_reuses_new_pdf_without_acceptance(tmp_path):
    from composition.pdf_source.production_profiles import (
        apply_profile,
        export_profile,
        from_spec,
        read_profile,
    )

    spec = sample(tmp_path)
    value = from_spec(spec, name="eMPF production", description="QR layouts")
    target = export_profile(tmp_path / "empf.pdpp", value)
    saved = target.read_text(encoding="utf-8")
    assert spec.source.path not in saved and spec.source.sha256 not in saved
    assert "classification_asset" not in saved and "accepted_at" not in saved
    loaded = read_profile(target)
    fresh = copy.deepcopy(spec)
    fresh.settings.groups = []
    fresh.settings.pages_per_envelope = 1
    fresh.detection_review = {}
    applied = apply_profile(fresh, loaded)
    assert applied.settings.groups == [] and not applied.detection_review.get("accepted")
    assert [o.template_ids for o in applied.objects][:2] == [["REGULAR"], ["REMINDER"]]
    assert asdict(applied.settings) == asdict(fresh.settings) and applied.media == fresh.media
    assert applied.needs_detection_review


@pytest.mark.parametrize("field", ["source", "groups", "accepted", "media", "duplex"])
def test_production_profile_rejects_source_or_production_state(tmp_path, field):
    from composition.pdf_source.production_profiles import from_spec, validate_profile

    value = from_spec(sample(tmp_path), name="eMPF")
    value[field] = "forbidden"
    with pytest.raises(CompositionError):
        validate_profile(value)


def test_classified_workflow_filters_original_envelope_and_keeps_layout(tmp_path):
    from composition.overlay.serializer import save_project
    from composition.pdf_source.classification import load_report
    from tests.production_approval import execute
    from tests.test_workflow_data_steps import insert
    from workflow.extraction import ExtractionSpec, ExtractionStore, Region
    from workflow.model import WorkflowRun, WorkflowSpec

    spec = sample(tmp_path)
    project = save_project(spec, tmp_path / "overlay.pdcx")
    workflow = WorkflowSpec.default().upgraded()
    workflow.node("input").params = {"paths": [spec.source.path]}
    workflow.node("extract").params = ExtractionSpec(
        [Region(name="Heading", x_mm=0, y_mm=0, width_mm=150, height_mm=50, required=False)]
    ).to_dict()
    workflow.node("overlay").params = {"path": str(project)}
    workflow.node("output").params = {"directory": str(tmp_path / "workflow-output")}
    run = execute(workflow, WorkflowRun(), tmp_path / "scratch", until="extract")
    assert not run.error, run.error
    result = scan_pdf(
        run.source,
        load_report(spec.detection_review)["profile"],
        cache_path=tmp_path / "workflow-index.sqlite",
    )
    report = accept_report(result["detection"], tmp_path / "workflow-audit")
    workflow.node("group").params = {"method": "reviewed_detection", "detection_review": report}
    workflow = insert(
        workflow,
        "group",
        "filter_records",
        {
            "mode": "all",
            "conditions": [
                {"field": "Heading", "operator": "contains", "data_type": "text", "value": "Reminder"}
            ],
        },
    )
    run = execute(workflow, run, tmp_path / "scratch")
    assert not run.error, run.error
    from workflow.inspection import inspect_step

    checked = inspect_step(workflow, workflow.node("overlay").id, tmp_path / "inspection")
    assert checked["result"]["status"] == "Checked", checked["result"]["error"]
    with ExtractionStore(run.database) as store:
        store.accept()
    run.accepted = True
    run = execute(workflow, run, tmp_path / "scratch", until="output")
    assert not run.error, run.error
    with fitz.open(run.output["output_pdf"]) as pdf:
        assert pdf.page_count == 2 and "REMINDER" in pdf[0].get_text()
        assert "REGULAR" not in pdf[0].get_text()
    with (Path(run.output["report_dir"]) / "classifications.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1 and rows[0]["TemplateID"] == "REMINDER"


def test_production_profile_rejects_oversize_schema_and_asset_escape(tmp_path):
    from composition.pdf_source.production_profiles import MAX_BYTES, from_spec, read_profile

    value = from_spec(sample(tmp_path), name="eMPF")
    path = tmp_path / "bad.pdpp"
    path.write_bytes(b"x" * (MAX_BYTES + 1))
    with pytest.raises(CompositionError):
        read_profile(path)
    value["schema_version"] = 2
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(CompositionError):
        read_profile(path)
    value["schema_version"] = 1
    value["layout"]["objects"][0]["element"]["font"]["file"] = "../outside.ttf"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(CompositionError):
        read_profile(path)


def test_template_map_tamper_is_not_reused_as_validated_asset(tmp_path):
    from composition.pdf_source.classification import load_report

    spec = sample(tmp_path)
    spec.detection_review["template_map"].reverse()
    with pytest.raises(CompositionError):
        load_report(spec.detection_review)
    from composition.overlay.generator import generate

    with pytest.raises(CompositionError, match="explicitly confirm production"):
        generate(OverlayJob(spec.to_dict(), str(tmp_path / "unapproved")))
    assert not (tmp_path / "unapproved").exists()


def test_i25_type_positions_preserve_existing_group_sheet_eog_semantics(tmp_path):
    spec = sample(tmp_path)
    for obj in spec.objects[:2]:
        obj.element.type = "i25"
        obj.element.width_mm = 70
        obj.element.height_mm = 12
        obj.profile = BarcodeProfile.inserter()
    result = overlay_generate(OverlayJob(spec.to_dict(), str(tmp_path / "i25-output")))
    assert result.status == "completed", result.error
    assert result.expected_barcodes == result.decoded_barcodes == 3
    plan = EnvelopePlan(spec.source.pages, spec.settings)
    expected = []
    for page in plan.pages():
        if page.fields()["Side"] == "Front":
            expected.append(BarcodeProfile.inserter().inserter_parts(page.fields()))
    assert [p["group"] for p in expected] == ["00", "00", "01"]
    assert [p["sheet"] for p in expected] == ["00", "01", "02"]
    with (Path(result.report_dir) / "barcodes.csv").open(encoding="utf-8-sig", newline="") as stream:
        actual = list(csv.DictReader(stream))
    assert [r["Payload"] for r in actual] == [p["payload"] for p in expected]


def test_customer_profile_identity_follows_application_and_output_audit(tmp_path):
    from composition.pdf_source.production_profiles import apply_profile, from_spec

    spec = sample(tmp_path)
    value = from_spec(spec, name="eMPF approved layout", revision=7)
    applied = apply_profile(spec, value)
    assert applied.customer_profile == {
        "profile_id": value["profile_id"],
        "name": value["name"],
        "revision": 7,
    }
    detection = scan_pdf(spec.source.path, value["detection_profile"], cache_path=tmp_path / "reused.sqlite")
    applied.settings.groups = detection["detection"]["groups"]
    applied.detection_review = accept_report(detection["detection"], tmp_path / "accepted-new")
    result = overlay_generate(OverlayJob(applied.to_dict(), str(tmp_path / "reused-output")))
    assert result.status == "completed", result.error
    audit = json.loads((Path(result.report_dir) / "job.json").read_text(encoding="utf-8"))
    assert audit["customer_production_profile"] == applied.customer_profile


def test_legacy_serialization_does_not_emit_new_empty_schema_fields(tmp_path):
    spec = sample(tmp_path)
    legacy = EnvelopeSpec(spec.source, EnvelopeSettings(pages_per_envelope=1))
    legacy.objects = [OverlayObject(Element(value="Legacy"))]
    raw = legacy.to_dict()
    assert raw["overlay_version"] == 8
    assert "template_ids" not in raw["objects"][0]
    assert "customer_profile" not in raw


def test_bounded_parts_preserve_template_routes_and_global_sequences(tmp_path):
    spec = sample(tmp_path)
    result = overlay_generate(
        OverlayJob(spec.to_dict(), str(tmp_path / "parts"), output_policy={"envelopes": 1})
    )
    assert result.status == "completed", result.error
    assert len(result.output_files) == 2
    for part, template, sequence, pages in zip(
        result.output_files, ["REGULAR", "REMINDER"], ["000001", "000002"], [4, 2], strict=True
    ):
        with fitz.open(part["output_pdf"]) as pdf:
            assert pdf.page_count == pages
            assert template in pdf[0].get_text() and sequence in pdf[0].get_text()
    assert result.expected_barcodes == result.decoded_barcodes == 3


def test_customer_profile_preserves_only_workflow_field_declarations(tmp_path):
    from composition.pdf_source.production_profiles import (
        apply_profile,
        export_profile,
        from_spec,
        read_profile,
    )

    spec = sample(tmp_path)
    spec.external_fields = ["Page_Account"]
    spec.objects.append(OverlayObject(Element(value="{{Page_Account}}")))
    spec.validate()
    value = from_spec(spec, name="eMPF workflow")
    target = export_profile(tmp_path / "workflow-layout.pdpp", value)
    loaded = read_profile(target)
    assert loaded["layout"]["external_fields"] == ["Page_Account"]
    assert "Page_Account" in target.read_text(encoding="utf-8")
    current = copy.deepcopy(spec)
    current.external_fields.append("Envelope_Account")
    applied = apply_profile(current, loaded)
    assert applied.external_fields == ["Page_Account", "Envelope_Account"]
    assert not applied.detection_review.get("accepted")
