"""Whole-envelope, bounded-output production integration regressions."""

from collections import namedtuple
from pathlib import Path

import fitz

from composition.production.model import ProductionJob
from composition.production.output_policy import OutputPolicy
from composition.template.model import Element, PageSpec, SequenceSpec, Template
from tests.production_approval import generate


def letter(count=5):
    return Template(
        name="Letter",
        record_mode="generated",
        generated_count=count,
        media={"duplex": True},
        sequences=[SequenceSpec(name="Seq", start=1)],
        pages=[PageSpec(elements=[Element(value="Record {{Seq}}")]) for _ in range(3)],
    )


def test_count_split_keeps_global_sequences_and_correct_physical_counts(tmp_path):
    policy = OutputPolicy.recommended().to_dict()
    policy["envelopes"] = 2
    result = generate(ProductionJob(letter().to_dict(), "", str(tmp_path), output_policy=policy))
    assert result.status == "completed", result.error
    assert result.generated_files == 3 and result.generated_pages == 20 and result.sheets == 10
    assert [p["records"] for p in result.output_files] == [2, 2, 1]
    assert [p["sheets"] for p in result.output_files] == [4, 4, 2]
    assert [p["pages"] for p in result.output_files] == [8, 8, 4]
    for index, item in enumerate(result.output_files, 1):
        assert f"part{index:06}" in item["output_pdf"]
        assert f"_{item['sheets']}SHT_{item['records']}ENV_D.pdf" in item["output_pdf"]
        with fitz.open(item["output_pdf"]) as pdf:
            assert f"Record {(index - 1) * 2 + 1:06}" in pdf[0].get_text()
            assert not pdf[3].get_text().strip()
    assert Path(result.report_dir, "outputs-manifest.json").is_file()
    assert not list(Path(result.report_dir).glob("chunk-*.pdf"))


def test_single_envelope_system_overflow_cannot_publish(tmp_path, monkeypatch):
    import composition.production.output_policy as limits

    monkeypatch.setattr(limits, "SYSTEM_MAX_BYTES", 100)
    result = generate(ProductionJob(letter(1).to_dict(), "", str(tmp_path)))
    assert result.status == "failed" and not result.output_pdf
    assert "envelope" in result.error.lower() and "exceeds" in result.error.lower()
    assert not list(Path(result.report_dir).rglob("*.pdf"))
    assert not list(Path(result.report_dir).rglob("*.ps"))


def test_no_policy_preserves_single_output_contract(tmp_path):
    result = generate(ProductionJob(letter(1).to_dict(), "", str(tmp_path), output_name="old.pdf"))
    assert result.status == "completed", result.error
    assert result.generated_files == 1 and Path(result.output_pdf).name == "old.pdf"
    assert Path(result.output_pdf).parent == Path(result.report_dir)
    assert not result.media_summary  # PDF-only must not invent a media configuration.


def test_pdf_byte_limit_refines_without_changing_visible_pages(tmp_path, monkeypatch):
    import composition.production.output_policy as limits

    baseline = generate(ProductionJob(letter(8).to_dict(), "", str(tmp_path / "base")))
    assert baseline.status == "completed", baseline.error
    cap = Path(baseline.output_pdf).stat().st_size - 100
    monkeypatch.setattr(limits, "SYSTEM_MAX_BYTES", cap)
    result = generate(ProductionJob(letter(8).to_dict(), "", str(tmp_path / "split")))
    assert result.status == "completed", result.error
    assert result.generated_files > 1
    with fitz.open(baseline.output_pdf) as original:
        global_page = 0
        for part in result.output_files:
            assert Path(part["output_pdf"]).stat().st_size <= cap
            with fitz.open(part["output_pdf"]) as document:
                for page in document:
                    assert page.get_text() == original[global_page].get_text()
                    assert (
                        page.get_pixmap(matrix=fitz.Matrix(0.3, 0.3)).samples
                        == original[global_page].get_pixmap(matrix=fitz.Matrix(0.3, 0.3)).samples
                    )
                    global_page += 1
        assert global_page == original.page_count


def test_cancel_after_one_part_discards_entire_unpublished_set(tmp_path):
    policy = OutputPolicy.recommended().to_dict()
    policy["envelopes"] = 1
    stopped = False

    def progress(_done, _total, message):
        nonlocal stopped
        if "Assembling part 2" in message:
            stopped = True

    result = generate(
        ProductionJob(letter(3).to_dict(), "", str(tmp_path), output_policy=policy),
        progress=progress,
        is_cancelled=lambda: stopped,
    )
    assert result.status == "cancelled" and result.generated_files == 0 and not result.output_files
    assert not list(tmp_path.rglob("*.pdf")) and not list(tmp_path.rglob("*.ps"))


def test_policy_change_after_review_is_rejected(tmp_path):
    from dataclasses import asdict

    import pytest

    from composition.production.generator import generate as engine
    from composition.review.authorization import ProductionAuthorization, ReviewSession
    from tests.production_approval import review_contexts

    job = ProductionJob(letter(1).to_dict(), "", str(tmp_path / "out"))
    session = ReviewSession.new()
    receipts = review_contexts(tmp_path / "review", [{"kind": "template", "job": asdict(job)}], session)
    job.output_policy = OutputPolicy.recommended().to_dict()
    with pytest.raises(ValueError, match="differ|changed"):
        engine(job, authorization=ProductionAuthorization(receipts, session))
    assert not (tmp_path / "out").exists()


def test_paired_ps_limit_refines_same_envelopes(tmp_path, monkeypatch):
    import composition.media.postscript as ps
    from tests.composition.test_postscript import ps_media

    template = letter(3)
    template.media = ps_media(duplex=True)

    # A deterministic converter stand-in tests the byte-boundary retry contract;
    # the existing PostScript module separately verifies real GS interpretation.
    def convert(directory, media, name, **kwargs):
        with fitz.open(Path(directory) / name) as pdf:
            count = pdf.page_count
        path = Path(directory) / Path(name).with_suffix(".ps")
        path.write_bytes(b"x" * (count * 150_000))
        return {"postscript": path.name, "postscript_pages": count}

    monkeypatch.setattr(ps, "export_postscript", convert)
    policy = OutputPolicy.recommended().to_dict()
    policy.update(envelopes=0, ps_bytes=1_000_000)
    result = generate(ProductionJob(template.to_dict(), "", str(tmp_path), output_policy=policy))
    assert result.status == "completed", result.error
    assert result.generated_files == 3
    assert [p["records"] for p in result.output_files] == [1, 1, 1]
    for part in result.output_files:
        assert Path(part["output_ps"]).stat().st_size <= 1_000_000
        assert Path(part["output_ps"]).stem == Path(part["output_pdf"]).stem


def test_i25_cycles_and_global_pages_continue_across_parts(tmp_path):
    import csv

    from tests.composition.test_inserter_production import template_for

    template = template_for(pages=1, count=101, duplex=False)
    policy = OutputPolicy.recommended().to_dict()
    policy["envelopes"] = 50
    result = generate(ProductionJob(template.to_dict(), "", str(tmp_path), output_policy=policy))
    assert result.status == "completed", result.error
    assert result.generated_files == 3 and result.decoded_barcodes == 101
    with Path(result.report_dir, "barcodes.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [r["Output page"] for r in rows] == [str(i) for i in range(1, 102)]
    assert [(rows[i]["Group sequence"], rows[i]["Sheet sequence"]) for i in (98, 99, 100)] == [
        ("98", "98"),
        ("99", "99"),
        ("00", "00"),
    ]
    with (
        Path(result.output_files[1]["output_pdf"])
        .with_name("barcodes.csv")
        .open(encoding="utf-8-sig", newline="") as stream
    ):
        local = list(csv.DictReader(stream))
    assert local[0]["Output page"] == "1" and local[0]["Envelope"] == "51"


def test_real_ps_parts_have_matching_names_and_local_media_pages(tmp_path):
    import csv
    import json

    from tests.composition.test_postscript import model, ps_media

    template = model(ps_media(duplex=True), count=3)
    policy = OutputPolicy.recommended().to_dict()
    policy["envelopes"] = 2
    result = generate(ProductionJob(template.to_dict(), "", str(tmp_path), output_policy=policy))
    assert result.status == "completed", result.error
    assert result.generated_files == 2
    for index, part in enumerate(result.output_files):
        folder = Path(part["output_pdf"]).parent
        report = json.loads((folder / "postscript-report.json").read_text())
        assert report["postscript"] == Path(part["output_ps"]).name
        assert report["postscript_pages"] == part["pages"]
        assert report["resolution_dpi"] == template.media["printer_profile"]["resolution_dpi"]
        assert part["printing"] == "D" and part["sheets"] == part["records"] * 3
        with (folder / "media-plan.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert rows[0]["File page"] == "1"
        assert rows[0]["Global output page"] == ("1" if index == 0 else "13")
        assert (folder / "job.json").exists() and (folder / "control.csv").exists()
    assert "MULTI-PART" in Path(result.report_dir, "SUBMISSION.txt").read_text()


def test_invalid_resolved_name_blocks_review_before_font_scan(tmp_path, monkeypatch):
    from dataclasses import asdict

    from composition.engine.renderer import Renderer
    from composition.review.service import create_review

    def forbidden(*args, **kwargs):
        raise AssertionError("Font scan must not start with invalid output naming")

    monkeypatch.setattr(Renderer, "prepare_fonts", forbidden)
    policy = OutputPolicy.recommended().to_dict()
    policy["naming"] = {"mode": "custom", "pattern": "{{job.missing}}_part{{part.number}}", "single": True}
    job = ProductionJob(letter(1).to_dict(), "", str(tmp_path / "out"), output_policy=policy)
    result = create_review(tmp_path / "review", {"kind": "template", "job": asdict(job)})
    assert result["status"] == "blocked"
    assert any("job.missing" in issue["reason"] for issue in result["issues"])


def test_refinement_rejects_reversed_whole_envelope_parts(tmp_path):
    from dataclasses import asdict

    import pytest

    from composition.review.authorization import ProductionAuthorization, ReviewSession
    from tests.production_approval import review_contexts

    job = ProductionJob(letter(2).to_dict(), "", str(tmp_path / "out"))
    session = ReviewSession.new()
    receipts = review_contexts(tmp_path / "review", [{"kind": "template", "job": asdict(job)}], session)
    grant = ProductionAuthorization(receipts, session)
    parts = [
        {"part": 1, "records": 1, "membership": [2], "key": ""},
        {"part": 2, "records": 1, "membership": [1], "key": ""},
    ]
    with pytest.raises(ValueError, match="order|number"):
        grant.require_partition_refinement(job.job_id, job.output_dir, OutputPolicy.from_dict(), parts, 2)


def test_single_flat_path_uses_actual_layout_budget(tmp_path):
    from composition.engine.assets import qpdf_executable
    from composition.media.planner import build_print_plan
    from composition.production.packages import build_packages
    from core.variables import VariableContext

    staging = tmp_path / "stage"
    staging.mkdir()
    chunk = staging / "chunk.pdf"
    with fitz.open() as pdf:
        pdf.new_page()
        pdf.save(chunk)
    final = Path("C:/") / ("x" * 220)
    assert len(str(final / "old.pdf").encode("utf-16-le")) // 2 <= 240
    assert len(str(final / "part000001" / "old.pdf").encode("utf-16-le")) // 2 > 240
    files, _, _ = build_packages(
        staging,
        final,
        [chunk],
        build_print_plan(Template(record_mode="generated", generated_count=1), 1),
        OutputPolicy.from_dict(),
        "old.pdf",
        VariableContext.for_job(),
        executable=qpdf_executable(),
    )
    assert files[0]["output_pdf"] == str(final / "old.pdf")


def test_media_inserted_blank_uses_production_source_mapping():
    from types import SimpleNamespace

    from composition.pdf_source.model import EnvelopeSettings
    from composition.pdf_source.planner import EnvelopePlan
    from ui.workspace_handoff import WorkspaceHandoffService

    messages = []
    opened = []
    service = SimpleNamespace(
        message=messages.append,
        open_linked_source=lambda *args: opened.append(args),
        _source_mapping_current=lambda *args: True,
    )
    session = SimpleNamespace(page=1, engine=SimpleNamespace(is_modified=False, revision=0))
    data = {
        "plan": EnvelopePlan(3, EnvelopeSettings(pages_per_envelope=3, duplex=True)),
        "spec": {},
        "revision": 0,
        "project": None,
        "part": {
            "global_page_ranges": [[1, 6]],
            "source_page_runs": [[1, 1, 1], [2, 2, None], [3, 3, 2], [4, 4, None], [5, 5, 3], [6, 6, None]],
        },
    }
    WorkspaceHandoffService._open_overlay_source(service, session, data)
    assert not opened and any("blank" in message.lower() for message in messages)
    session.page = 4
    WorkspaceHandoffService._open_overlay_source(service, session, data)
    assert opened == [(None, 2)]


def test_insufficient_scratch_space_blocks_before_rendering(tmp_path, monkeypatch):
    import shutil
    from dataclasses import asdict

    from composition.review.service import create_review

    monkeypatch.setattr(shutil, "disk_usage", lambda path: SimpleDisk(100, 100, 0))
    job = ProductionJob(letter(1).to_dict(), "", str(tmp_path / "out"))
    result = create_review(tmp_path / "review", {"kind": "template", "job": asdict(job)})
    assert result["status"] == "blocked"
    assert any("space" in issue["reason"].lower() for issue in result["issues"])


SimpleDisk = namedtuple("SimpleDisk", "total used free")


def test_known_system_part_limit_blocks_in_review(tmp_path, monkeypatch):
    from dataclasses import asdict

    import composition.production.output_policy as limits
    from composition.review.service import create_review

    monkeypatch.setattr(limits, "MAX_PARTS", 2)
    policy = OutputPolicy.recommended().to_dict()
    policy["envelopes"] = 1
    job = ProductionJob(letter(3).to_dict(), "", str(tmp_path / "out"), output_policy=policy)
    result = create_review(tmp_path / "review", {"kind": "template", "job": asdict(job)})
    assert result["status"] == "blocked"
    assert any("parts" in issue["reason"] for issue in result["issues"])


def test_part_summary_csv_escapes_formula_like_names(tmp_path):
    import csv

    result = generate(ProductionJob(letter(1).to_dict(), "", str(tmp_path), output_name="=letters.pdf"))
    assert result.status == "completed", result.error
    with Path(result.report_dir, "outputs.csv").open(encoding="utf-8-sig", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["PDF"] == "'=letters.pdf"
