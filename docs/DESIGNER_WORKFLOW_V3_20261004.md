# Document Designer home and executable workflow steps

Implementation date: 2026-10-04. Adds to the existing Mail Merge and PDF workflow implementation; this is not a public v3.0 release declaration.

## What users can now do

- Closing the last Designer project returns to a home with Letter Template, PDF Overlay and Visual Workflow cards, three quick-start recipes, and a unified cached recent-project list.
- Open a saved project from the recent list, remove an unavailable entry, or drop a project file to open it. Dropped PDF/data files ask which project type to create. PDFs can become multi-page letter backgrounds; there is no guessed data/template pairing.
- Insert a compatible step after a selected node, or drop it near an edge. Duplicate the five data transformation steps, move a step earlier/later, remove optional steps, and undo graph edits.
- Configure operations in ordinary forms. The inspector shows input/kept/excluded/issue counts and bounded before/after examples with stable source identities. Validation and exclusion CSVs can be opened from the inspector.
- Use the same prepared data for Mail Merge preview and generation. PDF workflows hand the selected, sorted complete envelopes and computed fields to Designer preview, barcode samples and production.
- Choose which output PDF to open when a job has split outputs.

## Seven added executable steps

| Step | Settings and behaviour |
| --- | --- |
| Clean Fields | Multiple trim, join-line, prefix-removal, case and literal replacement operations. |
| Create Fields | Constants, concatenation, zero padding, first/last characters. Existing fields require an explicit overwrite choice. |
| Filter Records | Existing structured All/Any conditions; excluded source IDs and reasons are retained. PDF workflows exclude whole envelopes after grouping. |
| Sort Records | Stable multi-key text/decimal sorting; empty values last. Invalid numeric values identify the source record. |
| Validate Data | Required, length, finite decimal and uniqueness checks. Both original and duplicate occurrences are reported; records are not silently deleted. Errors block production; warnings remain reviewable. |
| Running Sequence | Record/envelope or output-page scope, start/increment/padding/prefix/suffix. Sequence generation follows filtering/sorting and does not reset across split files. Existing template sequences are preserved; name collisions block checking. |
| Split Output | Field value or whole-record/envelope count. Names are sanitized, collisions block before generation, and a mailpiece is never divided between files. |

The graph remains a single typed path with up to 64 nodes. Page data can be cleaned, extended and validated before grouping; page filtering/sorting is prohibited. Filtering/sorting must precede the workflow sequence and split steps. Branches, arbitrary code and loops are not included.

## Storage, approval and production

- New UI workflows use `.pdflow` version 3. Version 1 PDF and version 2 Mail Merge files remain readable. Adding these nodes to a saved legacy project requires saving an upgraded copy; the original file is preserved.
- Node positions do not invalidate checked data. Settings and source changes invalidate affected results and approval.
- Prepared values, originals, exclusions, findings and source identities live in disk-backed SQLite snapshots. Sorting uses a bounded SQLite cache. Preview evidence is capped independently of input size.
- Saved batch companions omit customer preview samples and temporary snapshot paths. Reopening requires checking inputs again; production never starts automatically.
- PDF grouping continues to cover the entire original source. Production selection/order is a separate view, with original envelope and page provenance retained.
- Checked jobs reconcile original input = retained + excluded. An empty selection writes reports without creating an empty PDF.
- Split files are created privately, reopened/page-count checked and reconciled before publishing their enclosing directory. Cancellation removes unfinished split outputs. Completed jobs remain available.
- Final reports include `job.json`, control CSV, findings/exclusions/processed-record CSVs and source maps. Split logs list each output and its SHA256. The private composition log is explicitly named `composition-job.json`; original PDF boundaries are also retained.
- GUI workers own preparation and production. The engine, registry and transforms do not depend on Qt widgets. Existing qpdf, SQLite and renderer dependencies are reused; no new package or template/overlay format change is required.

## Files and integration

New modules:

- `composition/designer/home.py`, `recents.py`: home, cached recent projects and background availability checks.
- `workflow/registry.py`, `transforms.py`, `pipeline.py`: typed capabilities, data operations and reconciliation/partition planning.
- `workflow/pdf_pipeline.py`: original grouping plus separate production order, and one computed-field provider for Designer/barcode/production.
- `workflow/splitter.py`: cancellable qpdf splitting, output validation and atomic publication.
- `workflow/node_settings.py`: human-readable configuration and evidence inspector.

Integration is limited to the existing Designer project host/chrome, workflow model/canvas/workers/windows/batch executor, preview handoff and production report hook. `core/viewer.py` is unchanged. CI selectors include the new related core/UI tests; large benchmarks are not normal-commit gates.

## Verification

Targeted command:

Results: 113 related tests passed together; 8 CI selection tests also passed. Ruff passed on the changed Python modules. A subsequent focused PDF split check verifies the published-file count and retained original-boundary report.

```powershell
.\.venv-312\Scripts\python.exe -m pytest tests/test_workflow_core.py tests/test_workflow_ui.py tests/test_mail_merge_workflow.py tests/test_mail_merge_workflow_ui.py tests/test_workflow_data_steps.py tests/test_workflow_designer_home.py tests/composition/test_production.py -q
```

Coverage includes repeatable nodes and selected-step identity, legacy upgraded copies, invalid cached summaries, cancellation, duplicate identifiers, stable 10,000-row sorting, zero selection, page sequences across split files, multi-template batches and fixed Designer preview data. PDF fixtures exercise sorted envelopes of 2, 3 and 1 pages without changing original boundaries.

One existing UI expectation intentionally changed: the contextual next-step menu now includes compatible insertion actions alongside its existing next connection. Invalid base connections remain rejected.

Native viewport script: `scripts/workflow_ui_qa.py`. Captures light/dark, 960×640 and 1280×720 on the machine's actual 200% scaling. It asserts single-column home cards at 960 pixels, visible footer controls and a canvas height above 350 logical pixels. Measured workflow canvas heights: 446 and 526 pixels respectively. Screenshot artifacts are in the chat's `designer-v3-workflow` directory.

Data benchmark: `scripts/benchmark_workflow_data.py --records 1000 10000`. Single fresh-process samples on synthetic local text, importing SQLite rows then trimming and numeric sorting:

| Records | Seconds | Records/sec | Peak working set |
| ---: | ---: | ---: | ---: |
| 1,000 | 0.127 | 7,896 | 55.0 MiB |
| 10,000 | 0.803 | 12,446 | 58.1 MiB |

These are data-preparation smoke measurements, not PDF generation benchmarks, repeated medians or a real customer-document performance guarantee. Full application regression, Windows packaging, larger release benchmarks and actual inserter certification remain deferred to the user's consolidated release validation.
