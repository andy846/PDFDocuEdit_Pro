from __future__ import annotations

from scripts.ci_plan import CROSS_PLATFORM_TESTS, UI_TESTS, focused_tests, plan, run_tests


def test_branch_push_selects_relevant_tests_and_smoke() -> None:
    selected = focused_tests(["core/measurement.py", "tests/test_measurement.py"])
    assert "tests/test_measurement.py" in selected
    assert "tests/test_commands.py" in selected
    assert "tests/test_source_contract.py" in selected
    assert "tests/test_p1_ui.py" not in selected
    assert plan("push", "refs/heads/feature/measurement", ["core/measurement.py"]) == {
        "full": "false",
        "ui": "false",
        "cross_platform": "true",
        "focused_tests": " ".join(focused_tests(["core/measurement.py"])),
    }


def test_pr_and_merge_use_full_windows_suite_without_unrelated_platform_jobs() -> None:
    for event, ref in (("pull_request", "refs/pull/5/merge"), ("push", "refs/heads/main")):
        result = plan(event, ref, ["installer/PDFDocuEditPro.iss"])
        assert result["full"] == "true"
        assert result["ui"] == "false"
        assert result["cross_platform"] == "false"


def test_shared_and_ui_changes_enable_only_needed_extra_jobs() -> None:
    shared = plan("pull_request", "refs/pull/5/merge", ["core/measurement.py"])
    assert shared["cross_platform"] == "true"
    assert shared["ui"] == "false"
    ui = plan("pull_request", "refs/pull/5/merge", ["ui/deep_search_dialog.py"])
    assert ui["cross_platform"] == "true"
    assert ui["ui"] == "true"
    assert "tests/test_ui_smoke.py" in ui["focused_tests"]


def test_version_tag_runs_all_test_groups() -> None:
    result = plan("push", "refs/tags/v2.5.17", ["docs/RELEASE_NOTES_2.5.17.md"])
    assert result["full"] == result["ui"] == result["cross_platform"] == "true"


def test_workflow_inspector_changes_enable_windows_ui_gate() -> None:
    for path in ("workflow/inspection_ui.py", "workflow/drafts.py", "workflow/node_presentation.py"):
        result = plan("push", "refs/heads/feature/workflow", [path])
        assert result["ui"] == "true"
        assert "tests/test_ui_smoke.py" in result["focused_tests"]


def test_test_groups_exist_and_do_not_overlap() -> None:
    from scripts.ci_plan import TESTS

    assert not (set(UI_TESTS) & set(CROSS_PLATFORM_TESTS))
    assert all((TESTS.parent / path).is_file() for path in (*UI_TESTS, *CROSS_PLATFORM_TESTS))


def test_core_and_ui_jobs_do_not_repeat_modules(monkeypatch) -> None:
    from scripts import ci_plan

    calls = []
    monkeypatch.setattr(ci_plan.subprocess, "call", lambda command, **kwargs: calls.append(command) or 0)
    assert run_tests("core") == 0
    assert run_tests("ui") == 0
    core, ui = calls
    assert core[1:4] == ["scripts/regression_suite.py", "--group", "core"]
    assert ui[1:4] == ["scripts/regression_suite.py", "--group", "ui"]
    all_paths = {p.relative_to(ci_plan.ROOT).as_posix() for p in ci_plan.TESTS.rglob("test_*.py")}
    core_paths = all_paths - set(UI_TESTS)
    assert core_paths.isdisjoint(UI_TESTS)
    assert core_paths | set(UI_TESTS) == all_paths


def test_composition_changes_are_selected_recursively() -> None:
    selected = focused_tests(["composition/engine/renderer.py",
                              "tests/composition/test_workspace_modes.py"])
    assert "tests/composition/test_renderer.py" in selected
    assert "tests/composition/test_workspace_modes.py" in selected
    assert "tests/composition/test_models_data.py" in CROSS_PLATFORM_TESTS
    assert "tests/composition/test_workspace_modes.py" in UI_TESTS
    assert "tests/test_overlay_ui.py" in UI_TESTS
    core = plan("pull_request", "refs/pull/7/merge", ["composition/engine/renderer.py"])
    assert core["cross_platform"] == "true"
    assert core["ui"] == "false"
    designer = plan("push", "refs/heads/feature/print-composition-v3",
                    ["composition/designer/workspace.py"])
    assert designer["ui"] == designer["cross_platform"] == "true"


def test_focused_runner_accepts_composition_test_paths(monkeypatch) -> None:
    from scripts import ci_plan, regression_suite

    calls = []
    monkeypatch.setattr(regression_suite, "run",
                        lambda paths, output: calls.append((paths, output)) or 0)
    assert run_tests("focused", "tests/composition/test_renderer.py") == 0
    assert calls == [(["tests/composition/test_renderer.py"], ci_plan.ROOT / "build/ci-focused")]


def test_focused_isolation_keeps_every_selected_module_and_failure(monkeypatch):
    from scripts import regression_suite
    calls = []
    monkeypatch.setattr(regression_suite, "run", lambda paths, output: calls.append(paths) or 1)
    paths = ["tests/composition/test_designer_entry.py", "tests/composition/test_workspace_modes.py"]
    assert run_tests("focused", " ".join(paths)) == 1
    assert calls == [paths]


def test_mac_release_invokes_current_integrity_and_production_gates(monkeypatch):
    import runpy
    import sys

    import pytest

    import scripts.regression_suite as runner

    selected = []
    def capture(paths, output):
        selected.extend(paths)
        return 0

    monkeypatch.setattr(runner, "run", capture)
    monkeypatch.setattr(sys, "argv", ["macos_test_plan"])
    with pytest.raises(SystemExit) as result:
        runpy.run_module("scripts.macos_test_plan", run_name="__main__")
    assert result.value.code == 0
    assert {
        "tests/test_mutation_transactions.py", "tests/test_production_authorization.py",
        "tests/test_production_output_safety.py", "tests/test_production_recovery.py",
        "tests/test_workflow_branch_ui.py", "tests/test_document_windows.py",
        "tests/test_overlay_ui.py", "tests/test_error_recovery_lifecycle.py",
        "tests/test_queued_open_lifecycle.py",
    } <= set(selected)
    assert len(selected) == len(set(selected))



def test_qpdf_runtime_changes_require_platform_and_ui_gates():
    result = plan("pull_request", "refs/pull/14/merge", ["core/pdf_runtime.py"])
    assert result["full"] == result["ui"] == result["cross_platform"] == "true"
    for path in ("scripts/prepare_qpdf.py", "scripts/prepare_macos.py", "build_assets/composition/BUNDLE_INFO.json"):
        assert plan("pull_request", "refs/pull/14/merge", [path])["cross_platform"] == "true"
    assert "tests/test_pdf_runtime.py" in CROSS_PLATFORM_TESTS
    assert "tests/test_font_preflight.py" in CROSS_PLATFORM_TESTS


def test_measurement_viewer_suite_uses_shared_gui_lifecycle() -> None:
    # This suite creates overlays and full viewers, not only pure PDF metrics.
    assert "tests/test_measurement.py" in UI_TESTS
    assert "tests/test_measurement.py" not in CROSS_PLATFORM_TESTS
