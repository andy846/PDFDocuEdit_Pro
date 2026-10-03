from __future__ import annotations

import copy
from dataclasses import asdict

import pytest

from composition.designer.arrange import arrange
from composition.template.geometry import element_bounds
from composition.template.layout import arrange_elements
from composition.template.model import CompositionError, Element, Template
from tests.composition.test_layout_geometry import app, bounded_ui  # noqa: F401, F811
from tests.composition.test_pdf_overlay_models import sample_spec
from tests.composition.test_pdf_overlay_ui import finish
from tests.composition.test_workspace import close_window


def objects():
    return [asdict(Element(id=str(i), x_mm=x, y_mm=70+i*20, width_mm=w, height_mm=12, rotation_deg=a))
            for i, (x, w, a) in enumerate([(40, 25, 37), (90, 35, 0), (160, 20, 90)])]


@pytest.mark.parametrize("op,axis,edge", [("left", 0, 0), ("right", 0, 2), ("top", 1, 1), ("bottom", 1, 3)])
def test_rotated_align_and_input_immutable(op, axis, edge):
    raw = objects()
    original = copy.deepcopy(raw)
    result = arrange_elements(raw, [e["id"] for e in raw], op, (210, 297))
    assert raw == original
    assert len({round(element_bounds(e)[edge], 7) for e in result}) == 1
    assert all(e["font"] == original[i]["font"] and e["rotation_deg"] == original[i]["rotation_deg"] for i, e in enumerate(result))


def test_distribution_gap_reference_and_failure_atomic():
    raw = objects()
    result = arrange_elements(raw, [e["id"] for e in raw], "horizontal", (210, 297))
    b = sorted(map(element_bounds, result))
    assert b[1][0]-b[0][2] == pytest.approx(b[2][0]-b[1][2])
    assert result[0] == raw[0] and result[-1] == raw[-1]
    result = arrange_elements(raw, ["0", "1"], "gap_horizontal", (210, 297), gap=7)
    assert element_bounds(result[1])[0]-element_bounds(result[0])[2] == pytest.approx(7)
    result = arrange_elements(raw, ["0", "1"], "center", (210, 297), reference="page")
    assert all((element_bounds(e)[0]+element_bounds(e)[2])/2 == pytest.approx(105) for e in result)
    result = arrange_elements(raw, ["0", "1"], "same_size", (210, 297), reference="object", reference_id="2")
    assert all((e["width_mm"], e["height_mm"]) == (20, 12) for e in result)
    original = copy.deepcopy(raw)
    with pytest.raises(CompositionError, match="bounds"):
        arrange_elements(raw, ["0", "1", "2"], "gap_horizontal", (210, 297), gap=180)
    with pytest.raises(CompositionError, match="three"):
        arrange_elements(raw, ["0", "1"], "horizontal", (210, 297))
    assert raw == original


@pytest.mark.parametrize("overlay", [False, True])
def test_shared_arrange_one_undo_selection_zoom_and_reject(app, tmp_path, overlay):
    from composition.designer.overlay_workspace import OverlayWindow
    from composition.designer.workspace import CompositionWindow
    window = OverlayWindow() if overlay else CompositionWindow()
    try:
        if overlay:
            spec = sample_spec(tmp_path)
            spec.objects[1].element.x_mm = 60
            window.apply_spec(spec.to_dict())
        else:
            window._apply_template(Template(elements=[Element(**{k:v for k,v in e.items() if k not in {"font", "rules", "glyph_repairs"}}) for e in objects()]).to_dict())
        window.undo.clear()
        ids = [item.element.id for item in window.canvas.element_items]
        window.canvas.select_ids(ids)
        window.canvas.set_zoom(1.3)
        before = window.spec.to_dict() if overlay else window.template.to_dict()
        assert arrange(window, "left")
        assert window.undo.count() == 1 and set(window.canvas.selected_ids()) == set(ids)
        assert "arrange_tools" in window.actions
        after = window.spec.to_dict() if overlay else window.template.to_dict()
        assert not arrange(window, "gap_horizontal", gap=2000)
        assert (window.spec.to_dict() if overlay else window.template.to_dict()) == after
        assert window.undo.count() == 1
        window.undo.undo()
        assert (window.spec.to_dict() if overlay else window.template.to_dict()) == before
    finally:
        (finish if overlay else close_window)(window)
