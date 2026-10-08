"""Adapter to the shared PDF services; intermediates stay inside workflow scratch."""
import hashlib
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
    # Inspection roots already include a run identity. Keep private stage names
    # bounded instead of repeating full node IDs and increasingly long stems.
    stage = hashlib.sha256(node.id.encode("utf-8")).hexdigest()[:12]
    name = "result_flattened.pdf" if options.operation == "flatten" else "result_repaired.pdf"
    report = execute(plan, Path(root) / "pdf" / stage, output_name=name,
                     progress=progress, is_cancelled=is_cancelled)
    if report["status"] != "completed":
        raise CompositionError("PDF cleanup needs review. Use PDF Workspace to inspect and approve a repaired copy first.")
    return report
