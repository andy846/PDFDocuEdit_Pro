# Annotation, watermark and redaction transactions

Date: 2026-09-07. Follow-up to the page transaction and undo/redo reliability checkpoints. Source metadata remains V2.5.4.

## Completed

The shared viewer mutation boundary now covers annotation creation/removal, geometry, inline text, property editing, JSON import, text/image watermarks and application of redaction marks. Each successful action records one pre-action live snapshot. Propagated failures roll back the PDF and modified/revision state without clearing redo. Rollback refreshes annotation listings as well as primary/split/comparison canvas bindings.

Signature invalidation confirmation remains before mutations. The existing additional confirmation for permanent redaction application is preserved. Exporting annotations, flattened copies and summaries remain separate file-output operations.

JSON import uses an opt-in `strict_mutations` argument. Unsupported or invalid input records retain the existing skip/report behaviour. Actual application errors propagate in strict mode and cause the viewer's whole import batch to roll back. An import containing only skipped records creates no undo entry. The default headless import behaviour remains compatible; strict headless callers must own a transaction.

## Validation

Focused annotation, transaction and UI tests: **67 passed in 21.78 seconds**. The new 19 cases exercise real successful edits and failures after modification; successful actions undo/redo as one entry. Multi-page text/image watermarks and applied redactions are tested for rollback after the first modified page. **Full diagnostic run: 378 passed in 247.87 seconds across 33 modules** on Windows Python 3.12.14. An earlier quiet run was interrupted after apparently slow progress; it is not counted as passing validation. The verbose rerun completed without a test failure or per-test timeout.

Ruff, source verification and git diff whitespace checks passed. The new module is included in Linux/macOS core CI selection; those remote jobs were not executed here.

## Files and scope

`core/viewer.py`, `core/annotation_io.py`, new `tests/test_annotation_transactions.py`, and `.github/workflows/ci.yml`. Page actions retain the `_page_transaction` compatibility wrapper around the now-general `_mutation_transaction` boundary. No layout, theme, shortcut or version-metadata changes were made.

Further controller extraction and shared atomic IO remain separate architecture steps. Snapshots remain synchronous, in memory, and session-local; no crash-recovery persistence is claimed.
