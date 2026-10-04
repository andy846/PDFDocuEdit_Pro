# PDF Workspace → multi-page Mail Merge

## Operator workflow

1. Edit the Word-exported PDF in PDF Workspace. Saving the PDF first is optional.
2. Click **Send to Designer** and choose **Mail Merge Project** (the default).
3. Select Entire PDF, Current page or a page range. Each selected page becomes one fixed template page.
4. Import customer CSV/TXT/Excel data, place merge fields on the required template pages, and configure Running sequences or barcode objects.
5. Preview the customer and template page independently, then generate production output.

Three template pages and 398 customer records produce 1,194 pages, ordered as customer 1 pages 1–3, customer 2 pages 1–3, and so on. The PDF page count is never used as the customer count. Before data import the project has zero imported records.

**Per record** sequences keep the same value throughout one customer's template pages. **Per output page** sequences advance on each output page. Reference numbers can be imported data fields or independent sequence definitions. Code 128, I25 and QR reuse the existing variable-content renderer.

The toolbar, command palette, checked search results and Merge result's Send to Designer all use the same choice dialog. Direct Overlay and single-page background menu entries remain available. Create separate Mail Merge project bypasses duplicate-project focusing.

## Implementation and format

- `capture_template_pdf()` captures an editor document ID/revision under its existing lock, then creates independently owned, vector single-page backgrounds in the background task. It does not use Overlay's uniform-page-size inspector or mailpiece grouping. The 100-template-page limit is checked before snapshotting and in the choice dialog.
- Background import bakes annotation and widget appearances. Rotated pages are composed into a vector page of the exact visible cropped size; removing PDF rotation alone is insufficient for cropped pages. The source PDF is unchanged. Background text is static; merge objects are placed above it.
- `CapturedTemplatePdf` supplies `pages` and `link`; template format v9 stores source-link v2 with purpose `mail_merge_template` and `template_page_map` keyed by stable template page IDs. Existing template versions through v8 and source-link v1 remain readable. Saving writes v9; simply opening a legacy project does not rewrite its file.
- Reordering template pages preserves source lookup. Deleting a page or replacing/removing its background detaches only that page's link. Duplicate/added pages have no automatic original-source mapping.
- Existing `.pdcx` content-addressed asset storage saves every background. Moving the `.pdcx` together with its `.assets` folder keeps backgrounds usable even if the original PDF or temporary handoff directory no longer exists. Customer data uses the existing external-source configuration.
- Source updates preserve page IDs/order, merge objects, fonts, rules, data configuration and sequences. They require confirmation and validate bounds before replacement. A changed source selection/count offers a separate project; it does not move objects to guessed pages. Out-of-bounds replacements retain the old project. Undo keeps the older backgrounds available until project closure.
- Production output's original-source action resolves the saved production template page ID against its source mapping; modified source/output states retain the existing stale-mapping protection.
- Cancellation/failure discards unadopted temporary assets and creates no empty Designer tab. Engine and production code still have no dependence on Editor widgets. No dependencies or public application version were changed.

## Related fixes

The cropped/rotated background rendering defect was found by pixel comparison against the captured background. Backgrounds at 0°, 90°, 180° and 270° now keep their visible geometry and appearance.

Repeated project creation also triggered a Windows access violation while the status bar queried Qt's private layout-widget size hints during styling. Status-row height calculation now measures only visible labels, buttons and progress controls, with a re-entrancy guard. Existing footer layout and cancellation checks pass after this fix.

## Targeted verification

- New headless handoff cases: unsaved edits, annotations/widgets, mixed page sizes, crop/rotation visual equivalence, selected pages, immutable originals, portable saved assets, invalid mappings/version checks, cancellation/stale sources and the 100-page limit.
- End-to-end production: three template pages × two CSV customer records, correct six-page customer order, imported reference numbers, shared record sequences and page sequences. All six Code 128/I25/QR marks are decoded and checked against expected payloads. Job reconciliation and source mapping are checked.
- UI integration: default choice, strict page ranges, explicit Overlay choice, source updates preserving objects/view/Undo, changed page counts, invalid resized backgrounds, background removal/deletion, source tracing, cancellation cleanup and command-palette routing.
- Existing related handoff, multipage, sequence, renderer, engine-contract, page UI and compact-layout tests passed. Specific Excel/rules/rotation migration cases were retained with their canonical version assertion changed from v8 to v9. Merge's saved-list → generated result → Designer integration passed for both project types.
- The new UI integration and existing embedded-footer cases passed with `QT_SCALE_FACTOR=2`, including light/dark and narrow layouts.
- Ruff passed on the changed Python files. Full application regression and Windows packaging are deferred to the agreed final batch validation.

This update uses fixed template pages per customer. It does not add imposition, dynamic overflow pagination or automatic mailpiece detection to Mail Merge.
