# Mutation transaction / undo architecture — V2.6 preparation

Date: 2026-09-07. Source version metadata remains V2.5.4; this is an architecture checkpoint, not a packaged V2.6 release.

## Implemented behaviour

`PdfEngine.mutation_transaction(description)` holds DOCUMENT_LOCK for the whole action. The outermost scope serializes the live PDF once for rollback and history. Nested scopes share that rollback boundary, contribute no additional undo entry, and poison the outer scope on failure even if the caller catches the exception. A failed decorated engine operation also poisons the active transaction.

On success, a touched document commits one history entry through the owning session's recorder and advances revision once. The snapshot includes edits that were already unsaved when the action began. Empty transactions and unchanged rotation/reorder/delete selections preserve undo, redo and revision. Raw fitz edits must call `mark_modified()`; low-level methods do not silently create their own undo entries.

On failure, the engine restores PDF bytes, modified flag, full-save flag and revision, retaining document identity, save path, password and permissions. A rollback failure retains the existing explicit broken-engine/reopen error. Save, open, close and save-context replacement are excluded from active transactions.

`UndoStack.push_bytes()` writes the snapshot before changing history. Storage errors propagate and cause document rollback while preserving existing undo/redo. Obsolete snapshot cleanup errors are logged rather than corrupting a successfully committed history transition. The legacy file-copy snapshot APIs remain compatible.

The viewer uses `_page_transaction()` for rotation, deletion, insertion (single/repeated/blank), reordering and visual page plans, including thumbnail actions. Signature confirmation stays before the action. Readers finish pending renders before modification. If rollback replaces the fitz document, all primary, same-document split and external comparison canvases are rebound while preserving their view state. Engine replacement after undo/redo reconnects the session recorder.

## Files

- `core/pdf_engine.py`: explicit transaction API, recorder binding, lifecycle guards, nested failure handling; standalone insert/page-plan rollback remains supported.
- `core/undo.py`: strict byte-snapshot commit API and logged best-effort obsolete-file cleanup.
- `ui/document_session.py`, `core/viewer.py`: session recorder and all page-action boundaries.
- `tests/test_mutation_transactions.py`, `tests/test_ui_smoke.py`: failure and integration coverage.
- `.github/workflows/ci.yml`: transaction tests included in Linux/macOS core selection.

## Validation

**Full suite: 341 passed in 147.81 seconds, 32 modules**, on Windows Python 3.12.14. Zero failures/errors; the full-run log contains no native exception diagnostics. Focused engine/undo/transaction tests: 49 passed. UI smoke tests: 8 passed. Ruff, source verification and git diff whitespace checks passed.

The new cases cover a compound nested action, live unsaved snapshots, propagated and caught failures, preserved redo, failed snapshot storage, no-op actions, forbidden lifecycle calls, partial repeated insertion, and actual viewer undo/redo plus split-canvas rollback recovery.

## Limits and remaining architecture work

- This checkpoint migrates page actions. Annotation, watermark and other legacy mutation paths retain their existing snapshot APIs; undo/redo file-stack navigation itself has not been redesigned.
- Direct headless engine mutations require an explicit transaction for compound atomicity. A headless engine without a recorder provides rollback but no persistent undo history.
- Rollback snapshots remain in memory and serialization remains synchronous. The visual organizer additionally serializes its current input when it needs independent duplicate pages; that is not an extra undo entry.
- Transactions cover live PDF state, not external file writes or arbitrary caller-side effects. Do not save/export files inside a transaction expecting those writes to roll back.
- Further viewer decomposition and shared atomic IO are still separate steps. Remote CI, real macOS and physical printer validation were not run, and no installer was built or published.

## Subsequent follow-up

Undo/redo navigation was subsequently hardened to stage inverse snapshots and retain the previous engine until installation succeeds. See [undo/redo reliability report](UNDO_REDO_RELIABILITY_REPORT.md) for the superseding history-navigation implementation and test results. The limits above describe this transaction checkpoint.
