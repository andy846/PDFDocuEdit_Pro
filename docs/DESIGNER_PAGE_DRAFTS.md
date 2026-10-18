# Designer Add Page crash: incomplete media drafts

## Root cause

The development launch log confirmed an unhandled `CompositionError` in
`SequenceOperations._sequence_info()`, called while a `TemplateEdit.redo()`
updated the UI after Add Page. The new seventh template page had no Stock or
fallback. A sequence/barcode sample requested the strict print planner, which
correctly rejected that incomplete plan. Its exception escaped the Qt/Undo slot.

## Fix

- Catch expected `CompositionError` only while preparing UI sequence samples.
- Preserve source store, record count and fields; invalidate all derived sample
  rows rather than showing previous values or inventing production counters.
- Cache the explicit sample error with the existing UI cache and display the
  reason and Paper / Tray correction route in the Data summary.
- Retain Add Page, editing, Undo/Redo and saving/reopening incomplete projects.
- Preserve strict print planning and formal review/authorization. Generate PDF
  remains a review entry point; an incomplete Stock assignment cannot authorize
  generation. No implicit Stock selection or production-engine change.
- Unexpected programming errors remain diagnostic failures, not suppressed.

## Verification — 2026-10-18

The four initial focused cases reproduced the exact exception before the fix.
After the fix, 10 focused tests cover generated/imported data, I25 profiles,
page sequences, real plus-button clicks, source metadata, unavailable samples,
Undo/Redo, correction, profile-only records, project reopen, unexpected errors
and blocking formal production review.

Total related regression: **152 passed, 0 failed, 0 errors, 0 skipped** across
11 modules, including media/duplex, sequence values, multipage UI, I25
production, production review, Visual Workflow review and CI selection.
Targeted Ruff and Git whitespace checks passed.

Evidence is local and uncommitted under `build/probes/designer-plus/`.
Windows/PyQt6 offscreen automation; macOS and owner interactive checks remain
separate. No public-version, format, dependency, release or branch change.
