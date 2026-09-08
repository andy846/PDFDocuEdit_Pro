from __future__ import annotations

from io import BytesIO
from pathlib import Path

import fitz
from PIL import Image
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import core.verapdf as verapdf_module
from core.analysis import (
    AnalysisRequest,
    Finding,
    FindingSet,
    FindingSource,
    FindingStatus,
    InspectionReport,
    Severity,
    TextRule,
    ValidationStatus,
    _effective_dpi,
    _image_classification,
    inspect_and_analyze,
)
from core.pdf_engine import PagePlanEntry, PdfEngine
from core.platform_service import PlatformService, ProcessResult
from core.verapdf import (
    VeraPdfRuntime,
    command_for,
    find_verapdf_runtime,
    parse_verapdf_xml,
    validate_with_verapdf,
)
from ui.analysis_panel import AnalysisPanel
from ui.page_overlay import InteractionState, PageOverlay


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


def test_arrow_drag_uses_directional_endpoints_instead_of_a_marquee() -> None:
    app = QApplication.instance() or QApplication(["arrow-interaction-test"])
    overlay = PageOverlay(3)
    pixmap = QPixmap(240, 220)
    pixmap.fill(Qt.GlobalColor.white)
    overlay.set_pixmap(pixmap)
    overlay.show()
    app.processEvents()

    lines: list[list] = []
    selections: list[object] = []
    overlay.lineDrawn.connect(lambda _page, points: lines.append(points))
    overlay.selectionMade.connect(lambda _page, rect: selections.append(rect))
    overlay.set_line_mode(
        True,
        arrow=True,
        color="#cc2244",
        width=4.5,
        opacity=0.6,
    )
    assert overlay._interaction_state == InteractionState.LINE

    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(190, 160))
    QTest.mouseMove(overlay, QPoint(45, 35), delay=10)
    assert overlay._marquee is None
    assert overlay._preview is not None
    assert overlay._preview["kind"] == "arrow"
    assert overlay._preview["color"] == "#cc2244"
    assert overlay._preview["width"] == 4.5
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(45, 35))
    app.processEvents()

    assert selections == []
    assert len(lines) == 1
    assert [(round(point.x()), round(point.y())) for point in lines[0]] == [
        (190, 160),
        (45, 35),
    ]
    assert overlay._preview is None
    overlay.close()


def test_bundled_verapdf_uses_private_java_environment(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "VeraPDF"
    java = runtime_root / "jre" / "bin" / "java.exe"
    java.parent.mkdir(parents=True)
    java.write_bytes(b"runtime")
    jar = runtime_root / "bin" / "cli-1.30.2.jar"
    jar.parent.mkdir(parents=True)
    jar.write_bytes(b"cli")
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
        return ProcessResult(0, '<report isCompliant="true" />', "private diagnostic path")

    monkeypatch.setattr(
        verapdf_module, "find_verapdf_runtime", lambda _path=None: runtime
    )
    monkeypatch.setattr(verapdf_module.PlatformService, "run_cancellable", fake_run)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7\n")
    result = validate_with_verapdf(source, "2b")

    assert result.compliant is True
    assert result.message == "veraPDF validation completed successfully."
    assert "private diagnostic" not in result.message
    assert captured["command"][:3] == [str(java), "-jar", str(jar)]
    environment = captured["env"]
    assert environment["JAVA_HOME"] == str(runtime_root / "jre")
    assert str(runtime_root / "jre" / "bin") in environment["PATH"]


def _png_stream(mode: str = "RGB", size: tuple[int, int] = (300, 200)) -> bytes:
    image = Image.new(mode, size)
    if mode == "P":
        palette = [value for index in range(256) for value in (index, index, index)]
        image.putpalette(palette)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _fake_verapdf_runtime(tmp_path: Path, *, with_java: bool = True) -> VeraPdfRuntime:
    root = tmp_path / "veraPDF runtime"
    launcher = root / "verapdf.bat"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text("@echo off", encoding="utf-8")
    java_home = root / "jre"
    if with_java:
        java = java_home / "bin" / "java.exe"
        java.parent.mkdir(parents=True, exist_ok=True)
        java.write_bytes(b"java")
        jar = root / "bin" / "cli-1.30.2.jar"
        jar.parent.mkdir(parents=True, exist_ok=True)
        jar.write_bytes(b"jar")
    return VeraPdfRuntime(
        str(launcher),
        "Bundled veraPDF",
        str(root),
        str(java_home) if with_java else "",
    )


def test_effective_dpi_uses_transform_for_scale_and_rotation() -> None:
    base = {"width": 300, "height": 200, "bbox": (0, 0, 72, 48)}

    assert _effective_dpi({**base, "transform": (72, 0, 0, 48, 0, 0)}) == (
        300.0,
        300.0,
    )
    assert _effective_dpi({**base, "transform": (36, 0, 0, 24, 0, 0)}) == (
        600.0,
        600.0,
    )
    assert _effective_dpi({**base, "transform": (144, 0, 0, 96, 0, 0)}) == (
        150.0,
        150.0,
    )
    assert _effective_dpi({**base, "transform": (0, -72, 48, 0, 0, 72)}) == (
        300.0,
        300.0,
    )
    assert _effective_dpi({**base, "transform": (0, 0, 0, 0, 0, 0)}) == (
        0.0,
        0.0,
    )


def test_multiple_image_instances_use_each_placement_and_group_statistics(
    tmp_path: Path,
) -> None:
    source = tmp_path / "placements.pdf"
    stream = _png_stream(size=(300, 300))
    with fitz.open() as document:
        page = document.new_page(width=500, height=400)
        page.insert_image(fitz.Rect(36, 36, 108, 108), stream=stream)
        page.insert_image(fitz.Rect(160, 36, 304, 180), stream=stream)
        page.insert_image(
            fitz.Rect(340, 36, 412, 108), stream=stream, rotate=90
        )
        document.save(source)

    report = inspect_and_analyze(
        source,
        "placements",
        0,
        AnalysisRequest(preflight_profile="digital"),
    )
    low_dpi = [
        item for item in report.finding_set.findings if item.rule_id == "image.low_dpi"
    ]

    assert len(report.images) == 3
    assert [item["xdpi"] for item in report.images] == [300.0, 150.0, 300.0]
    assert len(low_dpi) == 1
    assert low_dpi[0].raw_data["effective_dpi"] == 150.0
    group = next(
        item
        for item in report.finding_set.groups()
        if item.rule_id == "image.low_dpi"
    )
    assert "Minimum: 150 DPI" in group.details
    assert "Threshold: 200 DPI" in group.details
    assert "Unique images: 1" in group.details


def test_indexed_rgb_image_is_visible_artwork_with_friendly_group(tmp_path: Path) -> None:
    source = tmp_path / "indexed.pdf"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_image(
            fitz.Rect(72, 72, 144, 120),
            stream=_png_stream("P"),
        )
        document.save(source)

    report = inspect_and_analyze(
        source,
        "indexed",
        0,
        AnalysisRequest(preflight_profile="general"),
    )

    assert report.images[0]["classification"] == "visible raster image"
    rgb_group = next(
        item for item in report.finding_set.groups() if item.rule_id == "image.rgb"
    )
    assert rgb_group.summary == "RGB images detected"
    assert rgb_group.details == (
        "RGB / Indexed RGB images are present in the document."
    )


def test_stencil_mask_does_not_participate_in_low_dpi_rule(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "mask.pdf"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_image(
            fitz.Rect(72, 72, 360, 360),
            stream=_png_stream(size=(10, 10)),
        )
        document.save(source)
    monkeypatch.setattr(
        "core.analysis._image_classification",
        lambda _document, _info: "stencil mask",
    )

    report = inspect_and_analyze(
        source,
        "mask",
        0,
        AnalysisRequest(preflight_profile="production"),
    )

    assert report.images[0]["classification"] == "stencil mask"
    assert not any(
        item.rule_id == "image.low_dpi" for item in report.finding_set.findings
    )


def test_image_classification_reads_pdf_imagemask_flag() -> None:
    class StencilDocument:
        @staticmethod
        def xref_get_key(_xref, key):
            assert key == "ImageMask"
            return "bool", "true"

    info = {
        "xref": 12,
        "width": 1,
        "height": 1,
        "bpc": 1,
        "colorspace": 0,
        "transform": (200, 0, 0, 200, 0, 0),
    }

    assert _image_classification(StencilDocument(), info) == "stencil mask"


def test_image_inside_form_xobject_uses_composed_transform(tmp_path: Path) -> None:
    form_source = tmp_path / "form-source.pdf"
    with fitz.open() as source_document:
        page = source_document.new_page(width=72, height=72)
        page.insert_image(
            fitz.Rect(0, 0, 72, 72),
            stream=_png_stream(size=(300, 300)),
        )
        source_document.save(form_source)

    target = tmp_path / "form-target.pdf"
    with fitz.open(form_source) as source_document, fitz.open() as target_document:
        page = target_document.new_page(width=300, height=300)
        page.show_pdf_page(fitz.Rect(36, 36, 180, 180), source_document, 0)
        target_document.save(target)

    report = inspect_and_analyze(
        target,
        "form",
        0,
        AnalysisRequest(preflight_profile="digital"),
    )

    assert len(report.images) == 1
    assert report.images[0]["xdpi"] == 150.0
    assert report.images[0]["classification"] == "visible raster image"
    assert any(
        item.rule_id == "image.low_dpi" for item in report.finding_set.findings
    )


def test_verapdf_missing_executable_is_unavailable(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(verapdf_module, "find_verapdf_runtime", lambda _path=None: None)

    result = validate_with_verapdf(tmp_path / "source.pdf", "2b")

    assert result.compliant is None
    assert result.message == "veraPDF executable was not found."
    assert result.summary.status == ValidationStatus.VALIDATOR_UNAVAILABLE


def test_verapdf_missing_java_is_unavailable(tmp_path, monkeypatch) -> None:
    runtime = _fake_verapdf_runtime(tmp_path, with_java=False)
    monkeypatch.setattr(
        verapdf_module, "find_verapdf_runtime", lambda _path=None: runtime
    )
    monkeypatch.setattr(verapdf_module.shutil, "which", lambda _name: None)

    result = validate_with_verapdf(tmp_path / "source.pdf", "2b")

    assert result.message == "Java runtime was not found."
    assert result.summary.status == ValidationStatus.VALIDATOR_UNAVAILABLE


def test_verapdf_nonzero_exit_is_validation_error(tmp_path, monkeypatch) -> None:
    runtime = _fake_verapdf_runtime(tmp_path)
    monkeypatch.setattr(
        verapdf_module, "find_verapdf_runtime", lambda _path=None: runtime
    )
    monkeypatch.setattr(
        verapdf_module.PlatformService,
        "run_cancellable",
        lambda *_args, **_kwargs: ProcessResult(7, "", "internal path omitted"),
    )

    result = validate_with_verapdf(tmp_path / "source.pdf", "2b")

    assert result.message == "veraPDF exited with status code 7."
    assert "internal path" not in result.message
    assert result.summary.status == ValidationStatus.ERROR


def test_windows_process_output_falls_back_from_utf8(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.platform_service.locale.getpreferredencoding",
        lambda _do_setlocale=False: "cp1252",
    )
    monkeypatch.setattr("core.platform_service.platform.system", lambda: "Windows")

    assert PlatformService._decode_process_output(b"caf\xe9") == "café"


def test_packaged_verapdf_path_resolution(tmp_path, monkeypatch) -> None:
    root = tmp_path / "dist internal"
    launcher = root / "verapdf" / "verapdf.bat"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("@echo off", encoding="utf-8")
    monkeypatch.setattr(verapdf_module, "bundle_root", lambda: root)
    monkeypatch.setattr(verapdf_module.shutil, "which", lambda _name: None)

    runtime = find_verapdf_runtime()

    assert runtime is not None
    assert Path(runtime.launcher) == launcher.resolve()
    assert runtime.backend == "Bundled veraPDF"


def test_direct_java_command_preserves_unicode_and_spaces(tmp_path) -> None:
    runtime = _fake_verapdf_runtime(tmp_path)
    source = tmp_path / "文件 with spaces.pdf"

    command = command_for(runtime, ["--format", "xml", str(source)])

    assert command[0].endswith("java.exe")
    assert command[1] == "-jar"
    assert command[-1] == str(source)
    assert "cmd.exe" not in command


def test_external_batch_command_preserves_unicode_and_spaces(tmp_path) -> None:
    if not PlatformService.WINDOWS:
        return
    root = tmp_path / "資料 folder"
    root.mkdir()
    launcher = root / "vera pdf.bat"
    launcher.write_text("@echo off\necho %~1", encoding="utf-8")
    source = root / "文件 source name.pdf"
    runtime = VeraPdfRuntime(
        str(launcher),
        "External veraPDF",
        str(root),
    )

    result = PlatformService.run(command_for(runtime, [str(source)]), cwd=root)

    assert result.returncode == 0
    assert "source name.pdf" in result.stdout


def test_analysis_panel_populates_inspector_categories(tmp_path) -> None:
    _app = QApplication.instance() or QApplication(["analysis-panel-test"])
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
    _app = QApplication.instance() or QApplication(["analysis-export-test"])
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
        "Severity,Category,Source,Rule,Summary,Page,Pages,Objects,Status,"
        "Details,ObjectRef,BBox,Value"
    )
    assert text.count("blank pages detected") == 1
    panel.close()


def test_repeated_nonblank_findings_group_by_rule_but_keep_details() -> None:
    findings = FindingSet(
        "group-rules",
        0,
        AnalysisRequest(),
        [
            Finding(
                FindingSource.PREFLIGHT,
                "font.not_embedded",
                Severity.ERROR,
                page,
                "Font is not embedded",
                f"Font resource on page {page + 1}",
                object_ref=f"{page + 10} 0 obj",
                category="Fonts",
            )
            for page in range(3)
        ],
    )

    groups = findings.groups()

    assert len(groups) == 1
    assert groups[0].count == 3
    assert groups[0].pages == (0, 1, 2)
    assert len(groups[0].findings) == 3
    assert "Font resource on page 1" in groups[0].details
    assert "10 0 obj" in groups[0].object_ref


def test_results_panel_groups_all_rules_and_action_buttons_fit() -> None:
    app = QApplication.instance() or QApplication(["analysis-layout-test"])
    finding_set = FindingSet(
        "panel-groups",
        0,
        AnalysisRequest(),
        [
            Finding(
                FindingSource.PREFLIGHT,
                "image.rgb",
                Severity.WARNING,
                page,
                "RGB image detected",
                f"Image on page {page + 1}",
                category="Color",
            )
            for page in range(4)
        ],
    )
    report = InspectionReport({}, [], [], [], {}, finding_set)
    panel = AnalysisPanel()
    panel.setFixedSize(390, 520)
    panel.set_report(report)
    panel.tabs.setCurrentIndex(3)
    panel.show()
    app.processEvents()

    assert panel.results.rowCount() == 1
    assert panel.results.item(0, 6).text() == "4"
    panel.group_results.setChecked(False)
    app.processEvents()
    assert panel.results.rowCount() == 4

    assert set(panel.result_action_buttons) == {
        "Select all",
        "Copy pages",
        "Export",
        "Extract",
        "Remove pages",
    }
    assert [action.text() for action in panel.export_actions_menu.actions()] == [
        "Page list (CSV)...",
        "",
        "Findings (CSV)...",
        "Findings (Excel)...",
    ]

    jumped: list[int] = []
    panel.jumpRequested.connect(jumped.append)
    panel.results.cellClicked.emit(2, 0)
    assert jumped == [2]

    results_tab = panel.tabs.widget(3)
    for button in panel.result_action_buttons.values():
        top_left = button.mapTo(results_tab, QPoint(0, 0))
        assert button.isVisible()
        assert top_left.x() >= 0
        assert top_left.x() + button.width() <= results_tab.width()
        assert top_left.y() + button.height() <= results_tab.height()
    panel.close()
