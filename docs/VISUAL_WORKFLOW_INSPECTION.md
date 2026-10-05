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

Composition checks perform full font/rule/output-plan checks, and can render one
requested record for preview. They do not invoke production generators, publish
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
