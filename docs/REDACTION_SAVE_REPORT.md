# Redaction save follow-up

Date: 2026-09-07. The user clarified that the reported interaction problem was a misunderstanding. Independent investigation nevertheless reproduced a separate save defect using a synthetic PDF; no user document was modified.

## Reproduction and fix

After applying a redaction, page text extraction returned no covered text, but a saved output still contained the original text in an old PDF stream. The normal incremental save path retains prior objects; a full write without garbage collection can also retain unreachable objects.

Applied redactions now set `requires_sanitized_save` on the engine. Saving such a document performs a complete write with garbage collection (`garbage=4`) before the existing PDF validation and atomic replacement. Encrypted output keeps its encryption policy while using the same garbage-collection requirement.

The requirement remains set across repeated saves because the live working document can still hold old objects. Undo/redo engine replacement inherits it conservatively. A failed mutation restores the previous requirement together with the other transaction state. Adding review marks alone does not enable this policy or remove content.

This removes unreachable redaction-related objects from generated output. It is not a promise to remove unrelated copies of information elsewhere in the document, attachments or external files. Session undo snapshots intentionally retain pre-redaction content to support Undo.

## Validation

Focused tests: **68 passed in 14.73 seconds**. Ordinary/encrypted outputs, repeated saves, failed transaction rollback and viewer undo/redo are covered. Tests check visible text, every decoded PDF stream, and unencrypted output bytes for the removed synthetic marker while confirming unrelated text remains.

An initial focused run triggered a native Qt access violation during UI fixture teardown. The initial application-lifetime adjustment passed the 68-case focused group, but its full run later exited early without a JUnit result. The final fixture keeps QApplication within the annotation test module, explicitly deletes closed windows, and drains background workers before module teardown. The reproduced ordering through the font-inspector tests then passed all 94 cases in 15.15 seconds. Neither failed/incomplete attempt is counted as successful validation. No production exception handler or diagnostic suppression was added.

**Final full suite: 389 passed in 255.95 seconds across 35 modules**, Windows Python 3.12.14, zero failures/errors. Ruff, source verification and git diff whitespace checks passed.

## Files and runtime

`core/pdf_engine.py`, `core/viewer.py`, `tests/test_redaction_save.py`, `tests/test_annotation_transactions.py`, and the core CI test selection.

The running interactive application was not closed or modified by these tests. It will load the source fix on its next start. No installer was built or published.
