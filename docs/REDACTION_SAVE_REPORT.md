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


## 2026-10-13 — Spot-colour image pixel redaction (development source)

A supplied five-page scan reproduced PyMuPDF 1.26.6's `only Gray, RGB, and CMYK colorspaces supported` error. The source contained Separation/Black images with DeviceCMYK alternate colour. The existing mutation transaction correctly restored the document; the generic rollback message obscured the native cause.

`core/redaction_images.py` now prepares only Separation/DeviceN image XObjects intersecting a redaction. It copies page Resources/XObject dictionaries and shared Form trees, embeds a process-colour Pixmap at native image dimensions, preserves soft masks and placement transforms, removes its temporary insertion stream/alias, and rewires the page-local image references. It does not replace the shared original image or rasterise the PDF page. Ordinary image-redaction modes remain unchanged.

The Viewer performs a read-only conversion count and adds a process-colour warning to the existing explicit confirmation. Cancelling preserves the image and marks. After approval, `apply_redaction_marks()` uses the existing native pixel-removal operation, reports conversions only after success, and treats a false backend result as failure. The same mutation/Undo/Redo and full garbage-collected atomic save are retained; no PDF-engine or project-format replacement.

### Current verification

- Seven new synthetic failure cases first reproduced the colour-space error; conversion tests then passed. Separate tests reproduced missing UI notices and a false-success backend return before their fixes.
- Final focused group: `test_redaction_images`, `test_redaction_save`, `test_annotation_transactions`, `test_annotations`, `test_p3_ui` — **106 passed in 33.47 seconds** on Windows, Qt offscreen. Ruff passed.
- Cases cover Separation/DeviceN, Indexed spot-colour bases, ordinary Indexed RGB/Gray compatibility, soft masks, repeated/shared images, shared nested Forms, inherited Resources, four rotations/CropBox, cancelling, Undo/Redo, rollback after an intermediate page, backend false result, visible pixels and decoded embedded image pixels, removal of original/unredacted orphan image streams, plus existing encrypted/repeated-save checks.
- The supplied sample's screenshot corresponds to page 3. A local-only test copy saved successfully: all five page sizes preserved; the other four pages render byte-for-byte identically; the original page-3 image stream is absent; the source SHA256 is unchanged; native 2480×3507 image dimensions retained. A separate Poppler rendering was visually checked. Private source/output files are not tracked or uploaded.

### Limits and operator review

Converting an affected image from spot to process colour necessarily changes ink-separation semantics. It may alter edge resampling: the sample's unmarked page-3 region has a mean per-channel difference of 0.126/255 and a maximum of 15/255. This is disclosed before approval; it is not a claim of pixel-identical spot-colour preservation. The other four pages remain exact. Operators should review output before production, and retain the original for spot-ink work.

This targets readable image XObjects, including nested Forms. It does not promise arbitrary damaged PDF/inline-image recovery. Unsupported cases still fail through the existing transaction. A source image legitimately visible in a different, unmarked placement can remain in that placement; unrelated copies, attachments and Undo snapshots are not scrubbed.

No public version change, installer packaging, GitHub release or macOS/printer real-device acceptance was performed for this focused development fix. Earlier full-suite counts above are historical and are not reused as validation of this update.


A fresh bounded code review found one further Indexed-palette case. The reviewer used PyMuPDF 1.25.4; four deterministic cases were independently reproduced on the project's pinned 1.26.6 before changing the implementation. Detection now inspects the decoded base colourspace for intersecting Indexed images, while ordinary Indexed RGB/Gray remain on the existing path. The four previously failing cases pass, including pre-apply conversion counts. No other actionable review findings were reported; no repeated broad review/testing cycle was run.
