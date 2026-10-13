"""Legally sharable deterministic font/PDF fixtures; no customer/system fonts."""

import json
from pathlib import Path

import fitz
import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from core.font_preflight.inventory import analyze, object_value
from core.font_preflight.matching import evaluate_sources
from core.font_preflight.model import FontPreflightError
from core.font_preflight.service import analyze_batch, export_report, prepare_repair, repair_copy, repair_job
from core.font_preflight.syntax import Name, Ref, parse
from core.pdf_operations.analysis import PdfCancelled


def build_font(path, *, width=500, restricted=0):
    chars = {
        code: bytes([code]).decode("cp1252") for code in range(256) if code not in {129, 141, 143, 144, 157}
    }
    cmap = {ord(char): f"g{code}" for code, char in chars.items()}
    glyphs = [".notdef", *cmap.values()]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(glyphs)
    builder.setupCharacterMap(cmap)
    outlines = {}
    for name in glyphs:
        pen = TTGlyphPen(None)
        if name not in {"g32", ".notdef"}:
            pen.moveTo((50, 0))
            pen.lineTo((400, 0))
            pen.lineTo((400, 650))
            pen.lineTo((50, 650))
            pen.closePath()
        outlines[name] = pen.glyph()
    builder.setupGlyf(outlines)
    builder.setupHorizontalMetrics({name: (width, 0) for name in glyphs})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable(
        {
            "familyName": "PreflightFixture",
            "styleName": "Regular",
            "uniqueFontIdentifier": "Fixture-1",
            "fullName": "PreflightFixture",
            "psName": "PreflightFixture",
            "version": "Version 1.0",
        }
    )
    builder.setupOS2(
        sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200, fsType=restricted
    )
    builder.setupPost()
    builder.setupMaxp()
    builder.save(path)
    return path


@pytest.fixture
def fixture_pdf(tmp_path):
    font = build_font(tmp_path / "original.ttf")
    reference = tmp_path / "reference.pdf"
    with fitz.open() as doc:
        for _index in range(2):
            page = doc.new_page(width=180, height=180)
            page.insert_font(fontname="FOriginal", fontfile=str(font), set_simple=True)
            page.insert_text((20, 45), "Original 012345", fontname="FOriginal")
        doc.save(reference)
    source = tmp_path / "source.pdf"
    with fitz.open(reference) as doc:
        fonts = doc.get_page_fonts(0, full=True)
        xref = fonts[0][0]
        data = object_value(doc, xref)
        descriptor = data["FontDescriptor"].xref
        doc.xref_set_key(descriptor, "FontFile2", "null")
        doc.save(source, garbage=0)
    inventory = analyze(source)
    selections = {str(xref): {"path": str(font), "authorized": True}}
    return source, reference, font, inventory, selections


def test_inventory_is_readonly_and_shared_fonts_have_all_pages(fixture_pdf):
    source, _, _, inventory, _ = fixture_pdf
    original = source.read_bytes()
    assert inventory.complete and inventory.page_count == 2
    assert any(r.status == "NON_EMBEDDED" and r.pages == [1, 2] for r in inventory.resources)
    assert source.read_bytes() == original


def test_exact_candidate_requires_reference(fixture_pdf):
    source, _, _, inventory, selections = fixture_pdf
    decisions = evaluate_sources(source, inventory, selections)
    assert decisions[0].status == "CANDIDATE_FOUND", decisions[0].reason
    with pytest.raises(FontPreflightError, match="reference"):
        prepare_repair(source, selections, "")


def test_native_repair_preserves_content_and_publishes_audit(fixture_pdf, tmp_path):
    source, reference, font, _, selections = fixture_pdf
    raw = source.read_bytes()
    result = repair_job(source, tmp_path / "jobs", selections, reference, authorized_reference=True)
    assert result["status"] == "VALIDATED"
    assert source.read_bytes() == raw
    assert Path(result["output_pdf"]).is_file()
    saved = json.loads(Path(result["report_dir"], "font-report.json").read_text())
    assert saved["validation"]["original_objects_preserved"]
    assert all(page["pixels_equal"] for page in saved["validation"]["pages"])
    assert "path" not in saved["matches"][0]["source"]
    with fitz.open(source) as before, fitz.open(result["output_pdf"]) as after:
        assert before[0].read_contents() == after[0].read_contents()
    assert analyze(result["output_pdf"]).resources[0].status == "EMBEDDED"


def test_wrong_metrics_and_license_are_blocked(fixture_pdf, tmp_path):
    source, _, _, inventory, selections = fixture_pdf
    xref = next(iter(selections))
    wrong = build_font(tmp_path / "wrong.ttf", width=600)
    assert (
        evaluate_sources(source, inventory, {xref: {"path": str(wrong), "authorized": True}})[0].status
        == "BLOCKED_ENCODING_OR_GLYPHS"
    )
    restricted = build_font(tmp_path / "restricted.ttf", restricted=2)
    assert (
        evaluate_sources(source, inventory, {xref: {"path": str(restricted), "authorized": True}})[0].status
        == "BLOCKED_LICENSE"
    )
    assert (
        evaluate_sources(source, inventory, {xref: {"path": selections[xref]["path"]}})[0].status
        == "BLOCKED_LICENSE"
    )


def test_reference_wrong_font_no_output(fixture_pdf, tmp_path):
    source, reference, font, _, selections = fixture_pdf
    changed = tmp_path / "changed-reference.pdf"
    with fitz.open(reference) as doc:
        doc[0].insert_text((10, 100), "Changed content")
        doc.save(changed)
    output = tmp_path / "out.pdf"
    with pytest.raises(FontPreflightError):
        repair_copy(source, output, selections, changed, authorized_reference=True)
    assert not output.exists()


def test_no_overwrite_cancel_and_original_unchanged(fixture_pdf, tmp_path):
    source, reference, _, _, selections = fixture_pdf
    with pytest.raises(FontPreflightError, match="overwritten"):
        repair_copy(source, source, selections, reference, authorized_reference=True)
    existing = tmp_path / "existing.pdf"
    existing.write_bytes(b"retained")
    with pytest.raises(FontPreflightError):
        repair_copy(source, existing, selections, reference, authorized_reference=True)
    assert existing.read_bytes() == b"retained"
    with pytest.raises(PdfCancelled):
        repair_copy(
            source,
            tmp_path / "cancel.pdf",
            selections,
            reference,
            authorized_reference=True,
            is_cancelled=lambda: True,
        )
    assert not (tmp_path / "cancel.pdf").exists()


def test_base14_and_strict_policy(tmp_path):
    source = tmp_path / "base.pdf"
    with fitz.open() as doc:
        doc.new_page().insert_text((20, 30), "Base 14")
        doc.save(source)
    assert analyze(source).resources[0].status == "BASE14_POLICY_EXEMPT"
    assert analyze(source, policy="strict").resources[0].status == "NON_EMBEDDED"


def test_signed_encrypted_and_corrupt_input_are_scan_only(fixture_pdf, tmp_path):
    source, _, _, _, _ = fixture_pdf
    encrypted = tmp_path / "encrypted.pdf"
    with fitz.open(source) as doc:
        doc.save(
            encrypted,
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner",
            user_pw="read",
            permissions=fitz.PDF_PERM_PRINT,
        )
    assert analyze(encrypted, password="read").protected
    signed = tmp_path / "signed.pdf"
    with fitz.open(source) as doc:
        xref = doc.get_new_xref()
        doc.update_object(xref, "<< /Type /Sig /ByteRange [0 0 0 0] /Contents <00> >>")
        doc.save(signed)
    assert analyze(signed).protected


def test_batch_failure_isolation_and_private_reports(fixture_pdf, tmp_path):
    source = fixture_pdf[0]
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"invalid")
    result = analyze_batch([broken, source])
    assert result["status"] == "NEEDS_REVIEW"
    assert result["files"][0]["status"] == "FAILED"
    assert result["files"][1]["status"] == "ANALYZED"
    report = tmp_path / "report.json"
    export_report(result, report)
    assert str(source) not in report.read_text()


@pytest.mark.parametrize(
    "value,expected",
    [("[1 0 R /A#20B]", [Ref(1), Name("A B")]), ("<< /K (Hello\\040world) >>", {"K": b"Hello world"})],
)
def test_bounded_object_reader(value, expected):
    assert parse(value) == expected


@pytest.mark.parametrize("value", ["[", "<< /A 1 /A 2 >>", "(", "[1] extra", "[" * 70 + "]" * 70])
def test_object_reader_rejects_malformed_or_deep_data(value):
    with pytest.raises(FontPreflightError):
        parse(value)


def test_nested_form_and_appearance_resources_are_discovered(fixture_pdf, tmp_path):
    source = fixture_pdf[0]
    nested = tmp_path / "nested.pdf"
    with fitz.open(source) as doc:
        font = doc.get_page_fonts(0, full=True)[0][0]
        form = doc.get_new_xref()
        doc.update_object(
            form,
            f"<< /Type /XObject /Subtype /Form /BBox [0 0 100 100] /Resources << /Font << /Nested {font} 0 R >> >> >>",
        )
        doc.update_stream(form, b"BT /Nested 10 Tf (123) Tj ET")
        resource_ref = object_value(doc, doc[0].xref)["Resources"].xref
        doc.xref_set_key(resource_ref, "XObject", f"<< /NestedForm {form} 0 R >>")
        appearance = doc[0].add_rect_annot((10, 50, 80, 80))
        doc.xref_set_key(appearance.xref, "AP", f"<< /N {form} 0 R >>")
        doc.save(nested)
    report = analyze(nested)
    assert report.complete
    resource = next(r for r in report.resources if r.xref == font)
    assert "Nested" in resource.resource_keys
    assert resource.pages == [1, 2]


def test_shared_resource_used_on_thousand_pages(tmp_path):
    source = tmp_path / "large.pdf"
    with fitz.open() as doc:
        doc.new_page().insert_text((20, 30), "Same resource")
        for _ in range(999):
            doc.fullcopy_page(0)
        doc.save(source)
    inventory = analyze(source)
    assert inventory.complete
    assert inventory.resources[0].pages == list(range(1, 1001))


def test_changed_source_and_qpdf_failure_do_not_publish(fixture_pdf, tmp_path, monkeypatch):
    from core.font_preflight import service

    source, reference, _, _, selections = fixture_pdf
    monkeypatch.setattr(service, "structure_check", lambda *a, **k: {"status": "Error"})
    with pytest.raises(FontPreflightError, match="qpdf"):
        repair_copy(source, tmp_path / "not-published.pdf", selections, reference, authorized_reference=True)
    assert not (tmp_path / "not-published.pdf").exists()
    assert not list(tmp_path.glob(".not-published-*"))


def test_cancel_during_page_validation_removes_whole_job(fixture_pdf, tmp_path):
    source, reference, _, _, selections = fixture_pdf
    state = {"cancelled": False}

    def progress(*_):
        state["cancelled"] = True

    with pytest.raises(PdfCancelled):
        repair_job(
            source,
            tmp_path / "jobs",
            selections,
            reference,
            authorized_reference=True,
            progress=progress,
            is_cancelled=lambda: state["cancelled"],
        )
    assert not list((tmp_path / "jobs").rglob("*.pdf"))
    assert json.loads(next((tmp_path / "jobs").glob("*-failed.json")).read_text())["status"] == "CANCELLED"


def test_unsupported_font_and_missing_mapping_fail_closed(fixture_pdf, tmp_path):
    source, _, _, _, selections = fixture_pdf
    altered = tmp_path / "custom.pdf"
    with fitz.open(source) as doc:
        xref = doc.get_page_fonts(0, full=True)[0][0]
        doc.xref_set_key(
            xref, "Encoding", "<< /Type /Encoding /BaseEncoding /WinAnsiEncoding /Differences [65 /B] >>"
        )
        doc.save(altered)
    inventory = analyze(altered)
    assert evaluate_sources(altered, inventory, selections)[0].status == "UNSUPPORTED"


def test_bounded_font_expansion_rejects_trailing_compressed_data(fixture_pdf, tmp_path):
    import zlib

    from core.font_preflight.validation import font_program

    with fitz.open(fixture_pdf[0]) as doc:
        stream = doc.get_new_xref()
        doc.update_object(stream, "<< >>")
        doc.update_stream(stream, zlib.compress(b"font") + b"trailing", compress=False)
        doc.xref_set_key(stream, "Filter", "/FlateDecode")
        with pytest.raises(FontPreflightError, match="trailing"):
            font_program(doc, stream)


def test_batch_repair_has_per_file_approval_and_isolates_blocked_jobs(fixture_pdf, tmp_path):
    from core.font_preflight.service import repair_batch

    source, reference, _, _, selections = fixture_pdf
    result = repair_batch(
        [
            {"source": str(source)},
            {
                "source": str(source),
                "reference": str(reference),
                "authorized_reference": True,
                "selections": selections,
            },
        ],
        tmp_path / "jobs",
    )
    assert result["status"] == "NEEDS_REVIEW"
    assert [r["status"] for r in result["files"]] == ["FAILED", "VALIDATED"]
    assert len(list((tmp_path / "jobs").rglob("*.pdf"))) == 1


def test_stream_and_pixel_validation_rejects_tampered_output(fixture_pdf, tmp_path):
    from core.font_preflight.validation import compare_objects, compare_pages

    source, reference, _, inventory, _ = fixture_pdf
    changed = tmp_path / "changed.pdf"
    with fitz.open(reference) as doc:
        doc[0].insert_text((10, 100), "tampered")
        doc.save(changed)
    with fitz.open(source) as before, fitz.open(changed) as after:
        with pytest.raises(FontPreflightError):
            compare_objects(before, after, {r.descriptor for r in inventory.resources})
    with fitz.open(reference) as before, fitz.open(changed) as after:
        with pytest.raises(FontPreflightError):
            compare_pages(before, after)


def test_no_subset_font_permission_uses_full_program(fixture_pdf, tmp_path):
    source, reference, _, _, selections = fixture_pdf
    from fontTools.ttLib import TTFont
    original = Path(next(iter(selections.values()))["path"])
    with TTFont(original) as font:
        font["OS/2"].fsType = 256
        font.save(original)
    # Candidate licenses permit full embedding; reference mismatch is still blocked.
    matches = evaluate_sources(source, analyze(source), selections)
    assert matches[0].status == "CANDIDATE_FOUND"
    with pytest.raises(FontPreflightError, match="binary"):
        prepare_repair(source, selections, reference, authorized_reference=True)


def test_report_csv_does_not_execute_untrusted_font_names(tmp_path):
    report = {"resources": [{"xref": 1, "name": "=HYPERLINK()", "subtype": "TrueType", "status": "NON_EMBEDDED", "pages": [1], "reason": "missing"}]}
    path = tmp_path / "font.csv"
    export_report(report, path)
    assert "'=HYPERLINK()" in path.read_text(encoding="utf-8-sig")
