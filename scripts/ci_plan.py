"""Select CI tests from changed files without repeating the full suite on pushes."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"

SMOKE_TESTS = ("tests/test_commands.py", "tests/test_source_contract.py")
UI_TESTS = (
    "tests/test_merge_workbench_ui.py",
    "tests/test_advanced_organizer.py",
    "tests/test_detailed_dialogs.py",
    "tests/test_entrypoint.py",
    "tests/test_large_organizer.py",
    "tests/test_low_resolution.py",
    "tests/test_organizer_audit.py",
    "tests/test_organizer_blank_dialog.py",
    "tests/test_organizer_rotation_regression.py",
    "tests/test_p1_ui.py",
    "tests/test_p2_ui.py",
    "tests/test_p3_ui.py",
    "tests/test_p4_ui.py",
    "tests/test_p5_ui.py",
    "tests/test_page_navigation_sync.py",
    "tests/test_page_overlay.py",
    "tests/test_scoped_shortcuts.py",
    "tests/test_search_page_actions.py",
    "tests/test_shortcut_customization.py",
    "tests/test_thumbnail_loading.py",
    "tests/test_tools_port.py",
    "tests/test_ui_regressions.py",
    "tests/test_ui_smoke.py",
    "tests/test_update_ui.py",
    "tests/test_windows_taskbar.py",
    "tests/test_overlay_ui.py",
    "tests/composition/test_auto_fallback.py",
    "tests/composition/test_bulk_typography.py",
    "tests/composition/test_canvas_continuity.py",
    "tests/composition/test_compact_layout.py",
    "tests/composition/test_designer_consolidation.py",
    "tests/composition/test_designer_controls.py",
    "tests/composition/test_designer_entry.py",
    "tests/composition/test_designer_hardening.py",
    "tests/composition/test_designer_usability.py",
    "tests/composition/test_document_designer.py",
    "tests/composition/test_excel_import.py",
    "tests/composition/test_glyph_repair_ui.py",
    "tests/composition/test_i25.py",
    "tests/composition/test_layout_geometry.py",
    "tests/composition/test_mailpiece_detection.py",
    "tests/composition/test_multipage_ui.py",
    "tests/composition/test_optional_overlay_barcode.py",
    "tests/composition/test_pdf_overlay_ui.py",
    "tests/composition/test_rules_ui.py",
    "tests/composition/test_sequences.py",
    "tests/composition/test_workspace.py",
    "tests/composition/test_workspace_modes.py",
    "tests/composition/test_workspace_handoff.py",
)
CROSS_PLATFORM_TESTS = (
    "tests/test_annotation_transactions.py",
    "tests/test_annotations.py",
    "tests/test_bookmarks.py",
    "tests/test_commands.py",
    "tests/test_deep_search.py",
    "tests/test_deep_search_detailed.py",
    "tests/test_font_inspector.py",
    "tests/test_ocr.py",
    "tests/test_io_atomic.py",
    "tests/test_mutation_transactions.py",
    "tests/test_pdf_engine.py",
    "tests/test_printing.py",
    "tests/test_redaction_save.py",
    "tests/test_search_detailed.py",
    "tests/test_settings.py",
    "tests/test_source_contract.py",
    "tests/test_stability_contracts.py",
    "tests/test_tasks.py",
    "tests/test_toc.py",
    "tests/test_undo_history.py",
    "tests/composition/test_models_data.py",
    "tests/composition/test_renderer.py",
)
ZERO_SHA = "0" * 40


def is_ui_change(path: str) -> bool:
    return path == "main.py" or path == "core/viewer.py" or path.startswith(
        ("ui/", "dialogs/", "styles/", "composition/designer/", "composition/preview/")
    ) or path in UI_TESTS


def is_cross_platform_change(path: str) -> bool:
    return path.startswith(("core/", "ui/", "dialogs/", "styles/", "updates/", "composition/")) or path in {
        "main.py", "launcher.py", "pyproject.toml", "requirements-base.txt", "requirements-dev.txt"
    } or path in CROSS_PLATFORM_TESTS


def focused_tests(paths: list[str]) -> tuple[str, ...]:
    selected = set(SMOKE_TESTS)
    test_sources = {
        path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in TESTS.rglob("test_*.py")
    }
    for path in paths:
        if path.startswith("tests/") and path in test_sources:
            selected.add(path)
        if path.endswith(".py") and "/" in path and not path.startswith("tests/"):
            before = len(selected)
            module = path.removesuffix(".py").replace("/", ".")
            candidate = f"tests/test_{Path(path).stem}.py"
            if candidate in test_sources:
                selected.add(candidate)
            parent, stem = module.rsplit(".", 1)
            for test_path, source in test_sources.items():
                if (f"from {module} import" in source or f"import {module}" in source
                        or f"from {parent} import {stem}" in source):
                    selected.add(test_path)
            if path.startswith("core/") and len(selected) == before:
                selected.add("tests/test_stability_contracts.py")
        if is_ui_change(path):
            selected.add("tests/test_ui_smoke.py")
        if path.startswith(("scripts/", "installer/", ".github/")) or path in {
            "PDFDocuEdit Pro.spec", "pyproject.toml", "requirements-base.txt",
            "requirements-dev.txt", "requirements-windows.txt",
        }:
            selected.add("tests/test_portable_build.py")
            selected.add("tests/test_update_release.py")
        if path.startswith(".github/") or path == "scripts/ci_plan.py":
            selected.add("tests/test_ci_plan.py")
    return tuple(sorted(selected))


def changed_paths(event: str, before: str, base_sha: str) -> list[str]:
    if event == "workflow_dispatch":
        return []
    if event == "pull_request":
        base = subprocess.check_output(
            ["git", "merge-base", "HEAD", base_sha], cwd=ROOT, text=True
        ).strip()
    elif before and before != ZERO_SHA:
        base = before
    else:
        base = subprocess.check_output(
            ["git", "merge-base", "HEAD", "origin/main"], cwd=ROOT, text=True
        ).strip()
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", "-z", base, "HEAD"], cwd=ROOT
    )
    return [item.decode("utf-8").replace("\\", "/") for item in changed.split(b"\0") if item]


def plan(event: str, ref: str, paths: list[str]) -> dict[str, str]:
    release = ref.startswith("refs/tags/v") or event == "workflow_dispatch"
    full = release or event == "pull_request" or ref == "refs/heads/main"
    return {
        "full": str(full).lower(),
        "ui": str(release or any(is_ui_change(path) for path in paths)).lower(),
        "cross_platform": str(release or any(is_cross_platform_change(path) for path in paths)).lower(),
        "focused_tests": " ".join(focused_tests(paths)),
    }


def run_tests(mode: str, tests: str = "") -> int:
    if mode == "focused":
        paths = tests.split()
        available = {item.relative_to(ROOT).as_posix() for item in TESTS.rglob("test_*.py")}
        if not paths or any(path not in available for path in paths):
            raise ValueError("Invalid focused test selection")
        command = [sys.executable, "-m", "pytest", *paths]
    elif mode == "core":
        command = [sys.executable, "-m", "pytest", *(f"--ignore={path}" for path in UI_TESTS)]
    elif mode == "ui":
        command = [sys.executable, "-m", "pytest", *UI_TESTS]
    elif mode == "cross":
        command = [sys.executable, "-m", "pytest", *CROSS_PLATFORM_TESTS]
    else:
        raise ValueError(f"Unknown test mode: {mode}")
    return subprocess.call(command, cwd=ROOT)


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "run":
        return run_tests(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
    if sys.argv[1:] != ["plan"]:
        raise SystemExit("Usage: ci_plan.py plan | run {focused|core|ui|cross} [test paths]")
    values = plan(
        os.environ["GITHUB_EVENT_NAME"],
        os.environ["GITHUB_REF"],
        changed_paths(
            os.environ["GITHUB_EVENT_NAME"],
            os.environ.get("GITHUB_EVENT_BEFORE", ""),
            os.environ.get("GITHUB_BASE_SHA", ""),
        ),
    )
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
