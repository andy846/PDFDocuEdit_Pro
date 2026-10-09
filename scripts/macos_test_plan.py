"""Bounded Mac port gates, using the existing isolated module runner."""
from pathlib import Path

from scripts.regression_suite import run

TESTS = [
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
    raise SystemExit(run(TESTS, Path("build/macos-tests")))
