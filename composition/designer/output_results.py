"""Select an already validated output; no new production or file scans."""

from pathlib import Path

from PyQt6.QtWidgets import QInputDialog


def choose_output(parent, result):
    files = result.get("output_files", [])
    if len(files) <= 1:
        return result.get("output_pdf", "")
    labels = [
        f"{Path(item['output_pdf']).name} | {item['sheets']:,} sheets | {item['records']:,} envelopes | {item['pages']:,} pages"
        for item in files
    ]
    choice, ok = QInputDialog.getItem(parent, "Open production output", "Choose a part", labels, 0, False)
    return files[labels.index(choice)]["output_pdf"] if ok else ""


def global_output_page(part, local_page):
    for first, last in part.get("global_page_ranges", []):
        count = last - first + 1
        if local_page <= count:
            return first + local_page - 1
        local_page -= count
    raise ValueError("This output page has no verified source mapping.")


def part_source_page(part, local_page):
    if type(local_page) is not int or local_page < 1:
        raise ValueError("Invalid output page.")
    for first, last, source in part.get("source_page_runs", []):
        if first <= local_page <= last:
            return None if source is None else source + local_page - first
    raise ValueError("This output page has no verified source mapping.")
