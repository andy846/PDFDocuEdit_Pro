# Visual Workflow: node inspection

## M1 — identity and drafts

Progress and repeated-step summaries use node IDs. Invalid live settings remain
attached to their node when navigating, and block save/run until repaired. Valid
settings use the existing undo stack. Workflow versions 1–4 remain readable;
v4 media flows use the same review pipeline as v3.

## M2 — safe checks

Select a node, choose one batch job for Mail Merge, and use **Check to this step**.
This checks the connected, typed source-to-target prefix even if later steps are
disconnected. Settings, Input, Output and Issues share the right panel.

Checks process the complete input. Snapshots and provenance are stored in SQLite
under the workspace's temporary directory; result tables fetch at most 50 rows.
Source IDs survive sort/filter. Output rows include bounded before/after values.
Search runs only on Enter. Displayed values are limited to 12 fields and 256
characters each; these limits do not limit processing or validation.
**Inspect field…** reads one selected field, including other columns, with a
64,000-character limit per before/after value and an explicit truncation notice.

Composition checks perform full font/rule/output-plan checks, and can render one
requested record for preview. Visible barcode payloads are checked with the same
payload validator as the renderer, across the complete input. This is not a final
rendering/decoding guarantee; production and physical device QC remain required.
Checks do not invoke production generators, publish
PDF/PS/JDF/report files, or approve jobs. PDF normalization and merge intermediates
can exist only inside the inspection scratch directory. Final production still
requires the existing full check and operator review.

Inspection results and statuses are independent of production. Live source/asset
hashes and prefix settings are checked before reading data or previewing. Changed
results must be checked again. Failed/cancelled issue evidence may be viewed as
historical evidence. Cancellation preserves completed snapshots. Window shutdown
waits for workers before deleting the workspace temporary directory.

### Targeted checks

`tests/test_workflow_inspection.py`: partial paths, full-data sort/unique checking,
paging, source provenance, stale sources/settings, cancellation, worker dispatch,
one-record preview, and explicit prohibition of production calls during inspection.

`tests/test_workflow_inspection_ui.py`: retained invalid drafts, node identity,
four tabs, explicit job choice, 50-row paging/search, separate approval state,
inline numeric edits and Undo.

Existing workflow UI and data-step tests are also run when shared code changes.
Full application regression, installer and release packaging remain deferred.

## M3 — browsing, layout and continuity

Tasks lock graph/settings edits and repeated checks. Canvas selection, pan, zoom,
completed result paging and scratch previews remain available. Inspection card
status/counts and settings summaries use node IDs; production status remains
separate. Cached checks return only the requested prefix, preventing a later
changed production setting from being presented as checked by an upstream cache.

The step library has Sources, Data preparation, Design and Production output
filters. Search matches names and descriptions. Add next step checks the actual
path/order and provides explanations for unavailable options. Compatible steps
can be inserted into an incomplete downstream draft.

Panel visibility and splitter widths are retained during this session. Narrow
windows offer Split view / Steps / Canvas / Details; full-width Details provides
room for larger editors. Common inline forms place labels above fields. View
contains Auto Layout / Fit / Reset, keeping the footer inside 960×640. Node tab,
search and page position are retained on navigation. Visual QA includes rendered
960×640 views at 200% scale in light/dark themes, using Windows UI fonts loaded
explicitly in the offscreen QA process; it does not change production font settings.

Additional tests cover busy read-only canvas interaction, incompatible step
explanations, panel visibility, single-panel layouts, invalidation scope, full-field
reading and exact source identity, including failures after sorting.

Visual findings fixed during this iteration included oversized footer controls,
inline form horizontal clipping, unnecessary nested scroll areas, empty details
pushing paging buttons below the viewport, and stale placeholder/icon contrast
after a theme change. Blank detail/plan regions are hidden until needed.
