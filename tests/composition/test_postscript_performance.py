"""Lossless converter input and bounded cancellation polling regressions."""
import hashlib
from pathlib import Path

import fitz
import pytest

import composition.media.postscript as ps
from composition.production.generator import JobCancelled
from tests.composition.test_postscript import ps_media


def repeated_pdf(path, *, cropped=True):
    with fitz.open() as background:
        page = background.new_page(width=210*72/25.4, height=297*72/25.4)
        page.insert_text((40, 60), "Repeated vector background 0123456789")
        with fitz.open() as document:
            for index in range(12):
                document.insert_pdf(background)
                if cropped:
                    document[-1].set_cropbox(fitz.Rect(10, 20, 390, 480))
                    document[-1].set_rotation(index % 4 * 90)
            document.save(path, deflate=True, garbage=1)


def test_export_deduplicates_only_private_converter_input(tmp_path, monkeypatch):
    from composition.media.ticket import export_rows

    source = tmp_path / "production.pdf"
    repeated_pdf(source, cropped=False)
    before = source.read_bytes()
    with fitz.open(source) as original:
        original_xrefs = original.xref_length()
    media = ps_media()
    export_rows(tmp_path, media,
                ([n, n, 1, "", n, "SINGLE", 1, "Front", "LH_A", ""] for n in range(1, 13)),
                12, source.name)
    run = ps._run
    captured = []

    def observe(executable, arguments, directory, is_cancelled, **kwargs):
        if "-sDEVICE=ps2write" in arguments:
            converter_input = Path(arguments[arguments.index("-f") + 1])
            assert converter_input != source
            assert converter_input.parent == Path(directory)
            assert "-r600" in arguments
            assert "-dEmbedAllFonts=true" in arguments and "-dSubsetFonts=true" in arguments
            with fitz.open(source) as a, fitz.open(converter_input) as b:
                assert b.xref_length() < original_xrefs
                assert len(a) == len(b) == 12
                for original, prepared in zip(a, b, strict=True):
                    assert (original.mediabox, original.cropbox, original.rotation) == (
                        prepared.mediabox, prepared.cropbox, prepared.rotation)
                    assert original.get_pixmap(dpi=144).samples == prepared.get_pixmap(dpi=144).samples
            captured.append(converter_input)
        return run(executable, arguments, directory, is_cancelled, **kwargs)

    monkeypatch.setattr(ps, "_run", observe)
    result = ps.export_postscript(tmp_path, media, source.name)
    assert result["postscript_pages"] == 12
    assert result["postscript_validation"] == "interpreted_page_count_and_size"
    assert source.read_bytes() == before
    assert captured and not captured[0].exists()
    assert not list(tmp_path.glob(".postscript-*"))


def dsc_fixture(tmp_path, lines=10000):
    source = tmp_path / "raw.ps"
    source.write_bytes(b"%!PS-Adobe-3.0\n%%EndProlog\n" + b"% data\n" * lines
                       + b"%%Page: 1 1\n%%BeginPageSetup\nshowpage\n%%EOF\n")
    return source


def test_media_polling_avoids_per_line_io_and_preserves_exact_output(tmp_path, monkeypatch):
    source = dsc_fixture(tmp_path)
    rows = [[1, 1, 1, "", 1, "SINGLE", 1, "Front", "LH_A", ""]]
    ps.program_dsc(source, tmp_path / "expected.ps", rows, ps_media(), 1, tmp_path / "expected.csv")
    checks = []
    monkeypatch.setattr(ps, "monotonic", lambda: 100.)

    def cancelled():
        checks.append(1)
        return False

    ps.program_dsc(source, tmp_path / "actual.ps", rows, ps_media(), 1, tmp_path / "actual.csv",
                   is_cancelled=cancelled)
    assert 1 <= len(checks) <= 5
    for suffix in ("ps", "csv"):
        assert hashlib.sha256((tmp_path / f"expected.{suffix}").read_bytes()).digest() == hashlib.sha256(
            (tmp_path / f"actual.{suffix}").read_bytes()).digest()


def test_cancel_before_media_copy_creates_no_output(tmp_path):
    source = dsc_fixture(tmp_path)
    with pytest.raises(JobCancelled):
        ps.program_dsc(source, tmp_path / "output.ps", [], ps_media(), 1, tmp_path / "audit.csv",
                       is_cancelled=lambda: True)
    assert not (tmp_path / "output.ps").exists()
    assert not (tmp_path / "audit.csv").exists()


def test_periodic_cancel_is_observed_inside_large_page_stream(tmp_path, monkeypatch):
    source = dsc_fixture(tmp_path)
    now = 0.
    checks = 0

    def clock():
        nonlocal now
        now += .01
        return now

    def cancelled():
        nonlocal checks
        checks += 1
        return checks >= 3

    monkeypatch.setattr(ps, "monotonic", clock)
    with pytest.raises(JobCancelled):
        ps.program_dsc(source, tmp_path / "output.ps", [], ps_media(), 1, tmp_path / "audit.csv",
                       is_cancelled=cancelled)
    assert .05 <= now <= .2
    assert (tmp_path / "output.ps").stat().st_size < 1024


def test_cancel_from_last_page_progress_is_checked_before_success(tmp_path):
    cancelled = False

    def progress(*event):
        nonlocal cancelled
        if event[0] == 1:
            cancelled = True

    with pytest.raises(JobCancelled):
        ps.program_dsc(dsc_fixture(tmp_path, lines=0), tmp_path / "output.ps",
                       [[1, 1, 1, "", 1, "SINGLE", 1, "Front", "LH_A", ""]], ps_media(), 1,
                       tmp_path / "audit.csv", is_cancelled=lambda: cancelled, progress=progress)


def test_preparation_preserves_crop_rotation_text_and_pixels(tmp_path):
    source, prepared = tmp_path / "source.pdf", tmp_path / "prepared.pdf"
    repeated_pdf(source)
    before = source.read_bytes()
    ps._prepare_converter_input(source, prepared)
    with fitz.open(source) as a, fitz.open(prepared) as b:
        assert len(a) == len(b) == 12
        assert b.xref_length() < a.xref_length()
        for original, page in zip(a, b, strict=True):
            assert (original.mediabox, original.cropbox, original.rotation) == (
                page.mediabox, page.cropbox, page.rotation)
            assert page.get_text() == original.get_text()
            assert page.get_pixmap(dpi=144).samples == original.get_pixmap(dpi=144).samples
    assert source.read_bytes() == before


@pytest.mark.parametrize("failure", ["cancel", "save", "geometry"])
def test_preparation_failure_never_reaches_converter_or_leaves_ps(tmp_path, monkeypatch, failure):
    from composition.template.model import CompositionError

    source = tmp_path / "production.pdf"
    repeated_pdf(source, cropped=False)
    before = source.read_bytes()
    cancelled = False
    save = fitz.Document.save

    def prepare_save(document, path, *args, **kwargs):
        nonlocal cancelled
        if failure == "save":
            raise OSError("disk full")
        result = save(document, path, *args, **kwargs)
        if failure == "cancel":
            cancelled = True
        if failure == "geometry":
            with fitz.open(path) as changed:
                changed[0].set_rotation(90)
                save(changed, path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
        return result

    def unexpected(*args, **kwargs):
        pytest.fail("Invalid/cancelled prepared input must not reach Ghostscript")

    monkeypatch.setattr(fitz.Document, "save", prepare_save)
    monkeypatch.setattr(ps, "_run", unexpected)
    error = {"cancel": JobCancelled, "save": OSError, "geometry": CompositionError}[failure]
    with pytest.raises(error):
        ps.export_postscript(tmp_path, ps_media(), source.name, is_cancelled=lambda: cancelled)
    assert source.read_bytes() == before
    assert not list(tmp_path.glob(".postscript-*"))
    assert not list(tmp_path.glob("*.ps"))
    assert not (tmp_path / "postscript-report.json").exists()


def test_cancel_at_preparation_progress_avoids_native_save(tmp_path):
    source = tmp_path / "missing-source.pdf"
    target = tmp_path / "prepared.pdf"
    cancelled = False

    def progress(*event):
        nonlocal cancelled
        cancelled = True

    with pytest.raises(JobCancelled):
        ps._prepare_converter_input(source, target, is_cancelled=lambda: cancelled, progress=progress)
    assert not target.exists()
