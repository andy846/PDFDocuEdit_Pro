"""Generated-data acceptance of the production features added after v3.0.1.

Called by the native/frozen smoke entry point; never uses customer files.
"""
from __future__ import annotations

import csv
from dataclasses import asdict
from pathlib import Path

import fitz


def run_new_features(output: Path) -> dict:
    from composition.designer.repeat_objects import repeat_selection
    from composition.designer.workspace import CompositionWindow
    from composition.engine.barcode_profiles import BarcodeProfile
    from composition.template.model import Element, PageSpec, Template
    from composition.template.serializer import save_project
    from scripts.composition_smoke import check, wait
    from workflow.branch_graph import add_route
    from workflow.model import WorkflowSpec

    output.mkdir(parents=True, exist_ok=True)
    window = CompositionWindow()
    window.show()

    # Use actual background workers: the frozen executable must dispatch these
    # operations too, rather than merely importing the engine in the QA process.
    def request(operation, **values):
        result, errors = [], []
        window._worker({"task": "workflow", "operation": operation, **values},
                       result.append, errors.append)
        wait(lambda: bool(result or errors), 120)
        check(not errors, f"Frozen {operation} failed: {errors}")
        wait(lambda: not window.workers)
        return result[0]

    model = WorkflowSpec.branched_mail_merge()
    model.node("route").params["routes"] = [{"id": "letters", "name": "A", "fallback": False,
        "condition": {"conditions": [{"field": "Scheme", "operator": "eq", "value": "A"}]}}]
    model = add_route(model, "B", {"conditions": [{"field": "Scheme", "operator": "eq", "value": "B"}]})
    branches = list(model.execution_plan().branches.values())
    for index, branch in enumerate(branches):
        template = Template(pages=[PageSpec(elements=[Element(value="{{Name}} / {{WorkflowSeq}}")])
                                   for _ in range(index+1)])
        branch[0].params["path"] = str(save_project(template, output/f"template-{index}.pdcx"))
    items = []
    for index in range(2):
        source = output/f"source-{index}.csv"
        source.write_text("Name,Scheme\nAlice,A\nBob,B\nCarol,A\nDan,B\n", encoding="utf-8")
        items.append({"id": f"source_{index}", "path": str(source), "options": {}})
    model.node("for_each").params["items"] = items
    shared = {"spec": model.to_dict(), "directory": str(output/"workflow")}
    run = request("branch_check", **shared)["run"]
    check((run["input"], run["routed"], run["exceptions"]) == (8, 8, 0), "Frozen route counts mismatch")
    check(len(run["jobs"]) == 4, "Frozen source/template jobs mismatch")
    check(not (output/"branch-output").exists(), "Check unexpectedly published files")
    evidence = request("branch_rows", run=run, **shared)
    check([row["sequence"] for row in evidence["rows"]] == [f"{i:06}" for i in range(1, 9)],
          "Frozen batch sequence changed")
    run = request("branch_approve", run=run, identities=[job["id"] for job in run["jobs"]], **shared)["run"]
    run = request("branch_run", run=run, output_dir=str(output/"branch-output"), **shared)["run"]
    check(run["status"] == "Completed" and run["published_records"] == 8, "Frozen route reconciliation failed")
    pages = 0
    for entry in run["jobs"]:
        with fitz.open(entry["batch"]["jobs"][0]["result"]["output_pdf"]) as document:
            pages += len(document)
    check(pages == 12, "Frozen branch page count mismatch")

    profile = BarcodeProfile.inserter().to_dict()
    template = Template(record_mode="generated", generated_count=2, media={"duplex": True}, pages=[
        PageSpec(id=f"page_{i}", elements=[Element(type="i25", width_mm=100, height_mm=14,
                                                   barcode_profile=profile)]) for i in range(3)])
    # No Media is needed: the inserter preset itself chooses duplex.
    before = template.to_dict()
    footer = Element(value="Reference {{EnvelopeSeq}}", x_mm=25, y_mm=275, width_mm=60, height_mm=8)
    before["pages"][0]["elements"].append(asdict(footer))
    repeated = repeat_selection(before, "page_0", [footer.id], ["page_1", "page_2"])
    check(all(page["elements"][-1]["x_mm"] == 25 and page["elements"][-1]["y_mm"] == 275
              for page in repeated["pages"]), "Cross-page coordinates changed")
    # Generate the barcode-only template; the footer check does not introduce
    # an unrelated merge field into generated-record production.
    window._commit(window.template.to_dict(), template.to_dict(), "Release inserter acceptance")
    window.start_production(str(output/"inserter"))
    wait(lambda: window.production_worker is None, 120)
    check(bool(window.last_output), window.production_summary.toPlainText())
    with fitz.open(window.last_output) as document:
        check(len(document) == 8, "Odd duplex record did not acquire its blank back")
    with Path(window.last_output).parent.joinpath("barcodes.csv").open(encoding="utf-8-sig", newline="") as stream:
        marks = list(csv.DictReader(stream))
    check(len(marks) == 4, "Frozen inserter front-side count mismatch")
    check([row["Payload"] for row in marks[:2]] == ["000000000000000000", "000100100000000006"],
          "Frozen zero-start payload mismatch")
    check([row["Sheet sequence"] for row in marks] == ["00", "01", "00", "01"], "Frozen sheet numbering mismatch")
    window.undo.setClean()
    window.close()
    wait(lambda: not window.workers)
    return {"conditional_sources": 2, "conditional_templates": 2, "published_records": 8,
            "branch_pages": pages, "inserter_pages": 8, "decoded_marks": len(marks),
            "zero_start_payloads": [row["Payload"] for row in marks[:2]], "repeat_coordinates": True}
