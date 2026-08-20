from __future__ import annotations

from pathlib import Path

import fitz
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QPixmap
import core.verapdf as verapdf_module
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from core.analysis import (
    AnalysisRequest,
    Finding,
    FindingSet,
    FindingSource,
    FindingStatus,
    Severity,
    TextRule,
    inspect_and_analyze,
)
from core.pdf_engine import PagePlanEntry, PdfEngine
from core.verapdf import VeraPdfRuntime, parse_verapdf_xml, validate_with_verapdf
from ui.analysis_panel import AnalysisPanel
from ui.page_overlay import InteractionState, PageOverlay
from core.platform_service import ProcessResult


def _make_analysis_pdf(path: Path) -> Path:
    with fitz.open() as document:
        first = document.new_page(width=595, height=842)
        first.insert_text((72, 96), "Invoice BAR-123")
        first.draw_rect(fitz.Rect(50, 130, 180, 220))
        document.new_page(width=595, height=842)
        document.save(path)
    return path


def test_finding_set_page_filter_and_stale_contract() -> None:
    request = AnalysisRequest(detectors=frozenset({"text"}))
    findings = FindingSet("doc-a", 3, request)
    assert findings.pages() == ()
    assert not findings.is_stale("doc-a", 3)
    assert findings.is_stale("doc-a", 4)
    assert findings.is_stale("doc-b", 3)


def test_inspector_and_smart_detection_are_zero_based(tmp_path: Path) -> None:
    source = _make_analysis_pdf(tmp_path / "analysis.pdf")
    request = AnalysisRequest(
        detectors=frozenset(
            {"exact_blank", "near_blank", "text", "specific_text", "vector"}
        ),
        preflight_profile="general",
        text_rule=TextRule("bar-123", case_sensitive=False, whole_word=False),
    )
    report = inspect_and_analyze(source, "doc", 7, request)

    assert report.overview["pages"] == 2
    assert len(report.pages) == 2
    assert report.finding_set.document_id == "doc"
    assert report.finding_set.revision == 7
    by_rule = {finding.rule_id: finding for finding in report.finding_set.findings}
    assert by_rule["detect.specific_text"].page == 0
    assert by_rule["detect.exact_blank"].page == 1
    assert any(
        item.rule_id == "detect.vector" and item.page == 0
        for item in report.finding_set.findings
    )


def test_page_plan_supports_duplicate_external_and_one_revision(tmp_path: Path) -> None:
    source = _make_analysis_pdf(tmp_path / "current.pdf")
    external = tmp_path / "external.pdf"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 96), "External page")
        document.save(external)

    engine = PdfEngine()
    engine.open(source)
    start_revision = engine.revision
    plan = [
        PagePlanEntry("a", "current", 0, final_rotation=90),
        PagePlanEntry("b", "external", 0, str(external), 0),
        PagePlanEntry("c", "current", 0, final_rotation=0),
    ]
    engine.apply_page_plan(plan)

    assert engine.page_count == 3
    assert engine.revision == start_revision + 1
    assert engine.document.load_page(0).rotation == 90
    assert "External page" in engine.document.load_page(1).get_text()
    assert "Invoice" in engine.document.load_page(2).get_text()
    engine.close()


def test_verapdf_xml_adapter_keeps_document_level_failures() -> None:
    xml = """<report isCompliant="false">
      <rule status="failed" specification="6.7.3" message="Metadata failed" />
      <rule status="failed" specification="7.1" message="Page failed">
        <context>pageNumber=4</context>
      </rule>
    </report>"""
    result = parse_verapdf_xml(xml, "2b")

    assert result.compliant is False
    assert len(result.findings) == 2
    assert result.findings[0].page is None
    assert result.findings[1].page == 3


def test_overlay_first_press_release_emits_once_and_state_is_exclusive() -> None:
    app = QApplication.instance() or QApplication(["overlay-interaction-test"])
    overlay = PageOverlay(0)
    pixmap = QPixmap(220, 220)
    pixmap.fill(Qt.GlobalColor.white)
    overlay.set_pixmap(pixmap)
    overlay.show()
    app.processEvents()

    selections: list[object] = []
    overlay.selectionMade.connect(lambda _page, rect: selections.append(rect))
    overlay.set_select_mode(True)
    assert overlay._interaction_state == InteractionState.SELECT
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    QTest.mouseMove(overlay, QPoint(120, 100), delay=10)
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(120, 100))
    app.processEvents()

    assert len(selections) == 1
    overlay.set_ink_mode(True)
    assert overlay._interaction_state == InteractionState.INK
    assert overlay._marquee is None
    overlay.set_note_mode(True)
    assert overlay._interaction_state == InteractionState.NOTE
    assert overlay._ink_points == []
    overlay.close()


def test_bundled_verapdf_uses_private_java_environment(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "VeraPDF"
    runtime = VeraPdfRuntime(
        str(runtime_root / "bin" / "verapdf.bat"),
        "Bundled veraPDF",
        str(runtime_root),
        str(runtime_root / "jre"),
    )
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return ProcessResult(0, '<report isCompliant="true" />', "")

    monkeypatch.setattr(
        verapdf_module, "find_verapdf_runtime", lambda _path=None: runtime
    )
    monkeypatch.setattr(verapdf_module.PlatformService, "run_cancellable", fake_run)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7\n")
    result = validate_with_verapdf(source, "2b")

    assert result.compliant is True
    environment = captured["env"]
    assert environment["JAVA_HOME"] == str(runtime_root / "jre")
    assert str(runtime_root / "jre" / "bin") in environment["PATH"]


def test_analysis_panel_populates_inspector_categories(tmp_path) -> None:
    app = QApplication.instance() or QApplication(["analysis-panel-test"])
    report = inspect_and_analyze(
        _make_analysis_pdf(tmp_path / "panel.pdf"), "doc", 0, AnalysisRequest()
    )
    panel = AnalysisPanel()
    panel.set_report(report)


def test_polygon_clicks_emit_real_vertices_on_double_click() -> None:
    app = QApplication.instance() or QApplication(["polygon-interaction-test"])
    overlay = PageOverlay(2)
    pixmap = QPixmap(220, 220)
    pixmap.fill(Qt.GlobalColor.white)
    overlay.set_pixmap(pixmap)
    overlay.show()
    app.processEvents()

    polygons: list[list] = []
    overlay.polygonDrawn.connect(lambda _page, points: polygons.append(points))
    overlay.set_polygon_mode(True)
    assert overlay._interaction_state == InteractionState.POLYGON
    QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=QPoint(150, 35))
    QTest.mouseDClick(overlay, Qt.MouseButton.LeftButton, pos=QPoint(80, 170))
    app.processEvents()

    assert len(polygons) == 1
    assert [(round(point.x()), round(point.y())) for point in polygons[0]] == [
        (20, 20),
        (150, 35),
        (80, 170),
    ]
    overlay.close()


def test_verapdf_parser_emits_unique_rules_not_child_checks() -> None:
    checks = "".join(
        f"""<check status="failed"><context>root/document[0]/pages[{index % 2}]
        ({index + 2} 0 obj PDPage)</context><errorMessage>DeviceRGB needs an
        output intent</errorMessage></check>"""
        for index in range(100)
    )
    xml = f"""<report isCompliant="false">
      <rule status="failed" specification="ISO 19005-4:2020" clause="6.2.4.3"
            testNumber="2" failedChecks="100">
        <description>DeviceRGB requires a valid DefaultRGB or output intent.</description>
        {checks}
      </rule>
      <rule status="failed" specification="ISO 19005-4:2020" clause="6.7.2.1"
            testNumber="1" failedChecks="1">
        <description>Required metadata is missing.</description>
        <check status="failed"><context>root/document[0]</context></check>
      </rule>
    </report>"""
    result = parse_verapdf_xml(xml, "4")

    assert len(result.findings) == 2
    assert all(item.rule_id != "verapdf.check" for item in result.findings)
    assert result.summary is not None
    assert result.summary.failed_rule_count == 2
    assert result.summary.failed_check_count == 101
    color = result.findings[0]
    assert color.category == "Color"
    assert color.pages == (0, 1)
    assert color.page is None
    assert "DeviceRGB" in color.summary
    assert color.raw_data["failed_checks"] == 100


def test_finding_normalization_preserves_distinct_page_occurrences() -> None:
    request = AnalysisRequest()
    first = Finding(
        FindingSource.PREFLIGHT,
        "image.low_dpi",
        Severity.WARNING,
        0,
        "Low effective image resolution",
    )
    second_page = Finding(
        FindingSource.PREFLIGHT,
        "image.low_dpi",
        Severity.WARNING,
        1,
        "Low effective image resolution",
    )
    findings = FindingSet("doc", 0, request, [first, first, second_page])

    findings.normalize()

    assert len(findings.findings) == 2
    assert findings.pages() == (0, 1)


def test_even_blank_pages_are_grouped_as_expected_duplex_pattern(
    tmp_path: Path,
) -> None:
    source = tmp_path / "duplex.pdf"
    with fitz.open() as document:
        for index in range(4):
            page = document.new_page()
            if index in {0, 2}:
                page.insert_text((72, 96), f"Content {index + 1}")
        document.save(source)

    report = inspect_and_analyze(
        source,
        "duplex",
        0,
        AnalysisRequest(
            detectors=frozenset({"exact_blank"}),
            preflight_profile="general",
        ),
    )
    blank_group = next(
        group
        for group in report.finding_set.groups()
        if group.group_id == "blank-pages"
    )

    assert blank_group.pages == (1, 3)
    assert blank_group.severity == Severity.INFO
    assert "even-numbered" in blank_group.details
    assert "duplex" in blank_group.details


def test_analysis_panel_status_and_grouped_csv_export(
    tmp_path: Path, monkeypatch
) -> None:
    app = QApplication.instance() or QApplication(["analysis-export-test"])
    source = tmp_path / "grouped.pdf"
    with fitz.open() as document:
        document.new_page().insert_text((72, 96), "Front")
        document.new_page()
        document.new_page().insert_text((72, 96), "Back")
        document.new_page()
        document.save(source)
    report = inspect_and_analyze(
        source,
        "grouped",
        0,
        AnalysisRequest(detectors=frozenset({"exact_blank"})),
    )
    panel = AnalysisPanel()
    panel.set_report(report)

    assert panel.results.rowCount() == 1
    assert "Issues: 1" in panel.status.text()
    assert "Affected pages: 2" in panel.status.text()

    panel.results.selectRow(0)
    panel._set_selected_status(FindingStatus.EXPECTED)
    assert "Issues: 0" in panel.status.text()
    assert "Expected: 1" in panel.status.text()

    target = tmp_path / "findings.csv"
    monkeypatch.setattr(
        "ui.analysis_panel.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: (str(target), "CSV (*.csv)"),
    )
    panel._export_csv()
    text = target.read_text(encoding="utf-8-sig")
    assert text.splitlines()[0] == (
        "Severity,Category,Source,Rule,Summary,Page,Pages,Count,Status,"
        "Details,ObjectRef,BBox,Value"
    )
    assert text.count("blank pages detected") == 1
    panel.close()
