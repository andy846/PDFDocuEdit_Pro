"""Shared readable node descriptions and settings summaries."""
from __future__ import annotations

from .registry import REGISTRY

CATEGORIES = ("Sources", "Data preparation", "Design", "Production output")
DESCRIPTIONS = {
    "input": "Load PDF sources and retain original source-page identities.",
    "data": "Import structured customer records from CSV, TXT or Excel data.",
    "merge": "Combine PDF sources in a chosen order and select source pages.",
    "extract": "Read named text regions from PDF pages using coordinates and rules.",
    "group": "Detect envelope boundaries from fixed page counts, identifiers or patterns.",
    "review": "Review page values and envelope boundaries before approving production.",
    "mapping": "Map source column names to reusable template field aliases.",
    "template": "Choose a letter template with text, fonts, backgrounds and barcodes.",
    "sequences": "Configure template sequence starts independently for each batch job.",
    "mail_review": "Validate all records and review a single-record preview before approval.",
    "overlay": "Add fields, sequences and inserter barcodes to completed PDF mailpieces.",
    "compose": "Compose production PDFs in the background after operator approval.",
    "output": "Validate production PDF output and write reconciliation reports.",
    "reports": "Publish validation and reconciliation reports with production output.",
}


def description(kind):
    return REGISTRY[kind].description or DESCRIPTIONS.get(kind, "")


def category(kind):
    if kind in ("input", "data", "merge"):
        return CATEGORIES[0]
    if kind in ("template", "overlay"):
        return CATEGORIES[2]
    if kind in ("review", "mail_review", "compose", "output", "reports", "media_assignment", "split_output"):
        return CATEGORIES[3]
    return CATEGORIES[1]


def settings_summary(node, fallback="Configure step"):
    params = node.params
    if node.kind in ("clean_fields", "create_fields", "sort_records", "validate_data", "filter_records"):
        key = {"clean_fields": "operations", "create_fields": "fields", "sort_records": "keys",
               "validate_data": "checks", "filter_records": "conditions"}[node.kind]
        rows = params.get(key, [])
        first = rows[0] if rows else {}
        action = first.get("operation", first.get("check", first.get("operator", first.get("type", ""))))
        return f"{first.get('field', '')}: {action}" + (f" +{len(rows)-1}" if len(rows) > 1 else "")
    if node.kind == "running_sequence":
        return f"{params.get('name')} · {params.get('start', 1)} / +{params.get('step', 1)}"
    if node.kind == "media_assignment":
        profile = params.get("printer_profile", {})
        backend = "PS" if profile.get("backend") == "postscript" else "JDF"
        return f"PDF + {backend} · {len(params.get('stocks', []))} stocks · " + ("Duplex" if params.get("duplex") else "Simplex")
    if node.kind == "split_output":
        return f"By {params.get('field')}" if params.get("method") == "field" else f"{params.get('count', 1000):,} per file"
    return fallback
