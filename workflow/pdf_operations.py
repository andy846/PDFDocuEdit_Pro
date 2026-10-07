"""Adapter to the shared PDF services; intermediates stay inside workflow scratch."""
from pathlib import Path

from composition.template.model import CompositionError
from core.pdf_operations.analysis import analyse
from core.pdf_operations.model import PdfOptions
from core.pdf_operations.service import execute


def process_pdf(node, source, root, *, progress=None, is_cancelled=None):
    if not source:
        raise CompositionError("Connect Merge PDFs before processing multiple sources.")
    options = PdfOptions.from_dict(node.params["options"])
    plan = analyse(source, options, progress=progress, is_cancelled=is_cancelled)
    report = execute(plan, Path(root) / "pdf-operations" / node.id,
                     progress=progress, is_cancelled=is_cancelled)
    if report["status"] != "completed":
        raise CompositionError("PDF cleanup needs review. Use PDF Workspace to inspect and approve a repaired copy first.")
    return report
