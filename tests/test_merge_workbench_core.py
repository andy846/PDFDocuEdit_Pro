from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import fitz
import pytest

from core.merge import (
    MergeItem,
    MergeSpec,
    export_merge_map,
    inspect_merge_source,
    load_merge_list,
    merge_pdf_items,
    save_merge_list,
    strict_pages,
)
from core.tools import ToolError


def source(path, count=5):
    with fitz.open() as pdf:
        for index in range(count):
            pdf.new_page().insert_text((30, 50), f"{path.stem} page {index+1}")
        pdf[0].insert_link({"kind": fitz.LINK_GOTO, "from": fitz.Rect(30, 30, 120, 55), "page": count-1})
        pdf[0].insert_link({"kind": fitz.LINK_GOTO, "from": fitz.Rect(130, 30, 220, 55), "page": 1})
        pdf[0].insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(230, 30, 320, 55), "uri": "https://example.org"})
        pdf[-1].set_rotation(90)
        pdf[0].add_text_annot((40, 80), "Keep annotation")
        pdf.save(path)
    return path


@pytest.mark.parametrize("value", ["0", "1-99", "5-2", "", "1,,2", "even"])
def test_strict_ranges_never_silently_clip(value):
    with pytest.raises(ToolError):
        strict_pages(value, 1 if value == "even" else 5)


def test_selected_merge_links_annotation_order_provenance(tmp_path):
    first, second = source(tmp_path/"first.pdf"), source(tmp_path/"second.pdf")
    result = merge_pdf_items(MergeSpec([MergeItem(str(first), [0, 4]), MergeItem(str(second), [2])], str(tmp_path/"out.pdf")))
    with fitz.open(result.output_path) as pdf:
        assert [p.get_text().strip() for p in pdf] == ["first page 1", "first page 5", "second page 3"]
        assert pdf[1].rotation == 90
        assert list(pdf[0].annots())[0].info["content"] == "Keep annotation"
        links = pdf[0].get_links()
        assert any(link.get("page") == 1 for link in links)
        assert any(link.get("uri") == "https://example.org" for link in links)
        assert len(links) == 2
    assert len(result.warnings) == 1
    assert [row["source_page"] for row in result.page_map] == [1, 5, 3]
    export_merge_map(result, tmp_path/"map.csv")
    with (tmp_path/"map.csv").open(encoding="utf-8-sig") as stream:
        assert len(list(csv.DictReader(stream))) == 3


def test_source_change_and_source_destination_rejected(tmp_path):
    path = source(tmp_path/"input.pdf")
    item = MergeItem(str(path), identity=inspect_merge_source(path))
    with pytest.raises(ToolError, match="cannot replace"):
        merge_pdf_items(MergeSpec([item], str(path)))
    item.identity["mtime_ns"] -= 1
    target = tmp_path/"out.pdf"
    target.write_bytes(b"existing output")
    with pytest.raises(ToolError, match="Source changed"):
        merge_pdf_items(MergeSpec([item], str(target)))
    assert target.read_bytes() == b"existing output"


def test_list_snapshot_portable_and_untrusted_schema(tmp_path):
    original = source(tmp_path/"temporary.pdf")
    item = {"id": "snapshot", "path": str(original), "label": "Open PDF", "selection": "all",
            "snapshot": True, "added": 0, "identity": {}}
    item["identity"] = inspect_merge_source(original)
    saved = save_merge_list(tmp_path/"list.pdmerge", [item])
    original.unlink()
    raw = load_merge_list(saved)
    assert Path(raw["items"][0]["path"]).parent == tmp_path/"list.assets"
    assert Path(raw["items"][0]["path"]).is_file()
    saved.write_text('{"merge_version":99}', encoding="utf-8")
    with pytest.raises(ToolError):
        load_merge_list(saved)


def test_twenty_sources_selected_pages_keep_originals_unchanged(tmp_path):
    paths = [source(tmp_path/f"letter-{i:02}.pdf") for i in range(20)]
    hashes = [hashlib.sha256(p.read_bytes()).digest() for p in paths]
    result = merge_pdf_items(MergeSpec([MergeItem(str(p), [0, 2, 4]) for p in paths], str(tmp_path/"delivery.pdf")))
    with fitz.open(result.output_path) as pdf:
        assert pdf.page_count == 60
        assert [page.get_text().strip() for page in pdf] == [f"letter-{i:02} page {p}" for i in range(20) for p in (1, 3, 5)]
    assert [hashlib.sha256(p.read_bytes()).digest() for p in paths] == hashes
    assert len(result.page_map) == 60
