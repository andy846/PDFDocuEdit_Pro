"""Preview resolution policy and actual headless raster output."""
from __future__ import annotations

import math

import fitz
import pytest

from composition.engine.preview_raster import (
    MAX_PREVIEW_EDGE,
    MAX_PREVIEW_PIXELS,
    bounded_scale,
    save_preview,
    screen_scale,
)
from composition.template.model import Element, Template
from composition.worker import dispatch
from tests.composition.test_pdf_overlay_models import sample_spec


def test_screen_zoom_and_high_dpi_use_more_pixels():
    width, height = 210 * 72 / 25.4, 297 * 72 / 25.4
    normal = screen_scale(width, height, 96 / 72)
    doubled = screen_scale(width, height, 2 * 96 / 72)
    assert normal == 2 and doubled == 4
    assert screen_scale(width, height, 1.4) == normal  # Same quality bucket.
    assert screen_scale(width, height, 4 * 96 / 72) > doubled


@pytest.mark.parametrize("size", [(595.276, 841.89), (34015.75, 34015.75), (72000, 720)])
def test_large_zoom_and_custom_pages_have_bounded_allocations(size):
    scale = bounded_scale(*size, 1_000_000)
    width, height = [math.ceil(length * scale) for length in size]
    assert width * height <= MAX_PREVIEW_PIXELS
    assert max(width, height) <= MAX_PREVIEW_EDGE
    assert scale == bounded_scale(*size, 32)


def test_native_raster_at_extreme_zoom_stays_within_budget(tmp_path):
    with fitz.open() as pdf:
        page = pdf.new_page(width=595.276, height=841.89)
        page.insert_text((40, 40), "Native allocation limit")
        result = save_preview(page, tmp_path / "bounded.png", 32)
    assert result["image_width"] * result["image_height"] <= MAX_PREVIEW_PIXELS
    assert max(result["image_width"], result["image_height"]) <= MAX_PREVIEW_EDGE


@pytest.mark.parametrize("values", [(0, 10, 2), (10, -1, 2), (10, 10, 0),
                                       (10, 10, float("nan")), (float("inf"), 10, 2)])
def test_bad_raster_parameters_rejected(values):
    with pytest.raises(ValueError, match="finite positive"):
        bounded_scale(*values)


@pytest.mark.parametrize("overlay", [False, True])
def test_worker_raster_scale_changes_only_preview_not_pdf_geometry_or_text(tmp_path, overlay):
    if overlay:
        spec = sample_spec(tmp_path)
        request = {"task": "overlay_preview", "project": spec.to_dict(), "envelope": 1, "print_page": 1}
        expected = "Original Source Page 1"
    else:
        expected = "Sharp text at every zoom"
        request = {"task": "preview", "template": Template(elements=[Element(value=expected)]).to_dict(),
                   "design": True}
    results, contents = [], []
    for scale in (2, 4):
        result = dispatch({**request, "raster_scale": scale, "target": str(tmp_path / f"preview-{scale}.pdf")})
        image = fitz.Pixmap(result["image"])
        assert (image.width, image.height) == (result["image_width"], result["image_height"])
        assert result["raster_scale"] == scale
        with fitz.open(result["pdf"]) as pdf:
            assert pdf.page_count == 1
            assert expected in pdf[0].get_text()
            contents.append((tuple(pdf[0].rect), pdf[0].get_text(), len(pdf[0].get_images())))
        results.append(result)
    assert contents[0] == contents[1]
    assert results[1]["image_width"] >= 2 * results[0]["image_width"] - 1
    assert results[1]["image_height"] >= 2 * results[0]["image_height"] - 1
