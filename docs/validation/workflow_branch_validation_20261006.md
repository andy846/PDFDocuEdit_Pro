# Conditional Mail Merge v5 — targeted validation

Date: 2026-10-06 · Windows local development checkout.

Implementation milestones: `6d14cab` (graph), `e0d7296` (headless engine),
`da0dfa6` (workspace), `46a2bf6` (preflight, production and traceability).
Existing duplex-stock/clipped-text fixes were preserved separately in `79aee92`.

## Automated checks

**156 related tests passed in 84.50 seconds.**

```text
.venv-312\Scripts\python.exe -m pytest
  tests/test_workflow_branch_graph.py tests/test_workflow_branch_engine.py
  tests/test_workflow_branch_ui.py tests/test_workflow_core.py
  tests/test_workflow_ui.py tests/test_workflow_inspection.py
  tests/test_workflow_inspection_ui.py tests/test_workflow_data_steps.py
  tests/test_workflow_designer_home.py tests/test_mail_merge_workflow.py
  tests/test_mail_merge_workflow_ui.py -q --tb=short
```

The command above is presented over lines for reading; invoke as one command.
Ruff passed for all modified Python modules/tests/benchmark/QA scripts.

Covered: v1–v4 compatibility; named v5 routes; cycles/nesting rejection;
source-to-step prefixes with unfinished downstream paths; three files × two
different templates (including different page counts); exclusive/no/ambiguous
match handling; batch sequence reservation; mapping and original identities
after sort/filter; cross-file uniqueness and correct validation-node issues;
blocked sources/fonts; explicit partial acknowledgement; real PDF generation;
record-to-output page ranges; cancelled production and manual continuation;
retained completed sibling outputs; Qt draft preservation/Undo; 50-row paging;
v5 host integration, saving/reopening and duplicate-tab prevention; unsaved open
Designer template protection; existing workflow and batch interfaces.

The combined suite exposed pre-existing narrow-layout constraints under the
actual global stylesheet. Splitting the PDF review controls into two rows and
allowing the zoom percentage label to shrink resolved these without disabling
tests or changing their assertions.

## UI evidence

`scripts/qa_workflow_branches.py` was run at normal scale and with
`QT_SCALE_FACTOR=2`. Both runs use the application's global stylesheet.
Dark/light themes, 1280×800 and 960×640, all three operation pages and the named
branch canvas were rendered and inspected. Evidence is in the ignored local
`build/branch-ui-qa/` folder.

Resolved: long acknowledgement forced a width above 960; hidden Build page kept
the compact layout when resizing back to wide; light-theme heading contrast;
unreadably small initial graph fit; ambiguous repeated-step names in the list.
The initial graph now uses a readable zoom with pan and a separate Fit action.
Compact layouts expose Steps/Canvas/Details; Apply/Revert remain outside the
scrollable properties area. Splitter widths survive compact/wide transitions.

## Performance evidence

Fresh worker process per dataset; three synthetic local CSV sources and two
template branches sharing a one-page text layout. Full import, routing,
snapshots and font/rule preflight precede generation. Actual generation includes
the existing PDF verification and output publication.

| Records / generated pages | Check seconds | Generation seconds | Peak worker memory |
| --- | ---: | ---: | ---: |
| 1,000 | 1.36 | 3.66 | 99.6 MiB |
| 10,000 | 2.04 | 20.56 | 100.2 MiB |
| 50,000 | 5.16 | 96.74 | 101.4 MiB |

Raw results: `workflow_branch_production_benchmark_20261006.json`,
`workflow_branch_50000_production_20261006.json`. Check-only 1k/10k/50k data is in
`workflow_branch_benchmark_20261006.json` (50k check: 4.88 s / 96.5 MiB).

These are single-run measurements, not medians or a physical-printer guarantee.
They show bounded worker memory for this synthetic fixture. The fixture does
not cover network sources, large images, CJK font load, complex customer rules
or printer paper selection. Benchmarks were captured during M4 development;
the final additional human-readable CSV trace columns were verified by targeted
generation tests after the benchmark run. The script supports repeating them.

## Delivery boundaries

README and Help → README describe the new entry and operator sequence.
Public version and template schema are unchanged. This is a local development
delivery; no installation package, full editor regression, printer proof,
GitHub release or automatic restart/resume was performed this round.
