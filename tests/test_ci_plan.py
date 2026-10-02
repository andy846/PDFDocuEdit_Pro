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
    assert all(f"--ignore={path}" in core for path in UI_TESTS)
    assert ui[3:] == list(UI_TESTS)


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
    from scripts import ci_plan

    calls = []
    monkeypatch.setattr(ci_plan.subprocess, "call",
                        lambda command, **kwargs: calls.append(command) or 0)
    assert run_tests("focused", "tests/composition/test_renderer.py") == 0
    assert calls[0][3:] == ["tests/composition/test_renderer.py"]
