"""Bounded Mac port gates, using the existing isolated module runner."""
import argparse
from pathlib import Path

from scripts.regression_suite import run

TESTS = [
    "tests/test_unified_release.py",
    "tests/test_macos_auth_updates.py", "tests/test_updates.py", "tests/test_update_ui.py",
    "tests/test_private_auth.py", "tests/test_private_auth_ui.py",
    "tests/test_macos_parity.py", "tests/test_entrypoint.py", "tests/test_printing.py",
    "tests/test_tools_port.py", "tests/test_mutation_transactions.py", "tests/test_io_atomic.py",
    "tests/test_pdf_operations.py", "tests/test_variables.py", "tests/test_v2_analysis.py",
    "tests/composition/test_system_fonts.py", "tests/composition/test_excel_import.py",
    "tests/composition/test_multipage_ui.py", "tests/composition/test_pdf_overlay_ui.py",
    "tests/composition/test_inserter_production.py", "tests/composition/test_postscript.py",
    "tests/composition/test_production_review.py", "tests/composition/test_production_review_ui.py",
    "tests/composition/test_workspace_modes.py", "tests/test_workflow_production_review.py",
    "tests/test_workflow_branch_engine.py", "tests/test_workflow_inspection.py",
]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auth-updates", action="store_true", help="Only repeat the account/update and application lifecycle gates")
    args = parser.parse_args()
    selected = TESTS
    if args.auth_updates:
        selected = TESTS[:8] + ["tests/test_mutation_transactions.py", "tests/test_io_atomic.py",
                               "tests/composition/test_workspace_modes.py"]
        selected += ["tests/test_private_auth_build.py", "tests/test_update_release.py"]
    raise SystemExit(run(selected, Path("build/macos-tests")))
