# PDF Workspace ↔ Document Designer handoff

Implemented 2026-10-03. This is a development update, not a public release or a Windows packaging acceptance record.

## User workflow

1. In PDF Workspace, choose **Send to Designer** on the main command bar. The primary action sends the entire current PDF to a new overlay project, including applied, unsaved edits. The dropdown offers current-page overlay, current-page template background, and a separate overlay project. Narrow windows retain the icon and tooltip.
2. Normal Search checked-page actions also offer **Send to Designer**. Pages are deduplicated in source order; stale search results must be refreshed before transfer.
3. A transferred overlay starts with no objects or machine barcode. Its one-page grouping is provisional: confirm fixed grouping or review detected mailpieces before production.
4. **Linked PDF** shows source status, **Open source**, and **Update source**. Updating is explicit, presents page-count/geometry changes, keeps objects/fonts/barcode profiles, and can be undone. Changed geometry or invalid object scopes must be reviewed. Dynamic grouping acceptance is invalidated on update.
5. Save the project to keep a private PDF snapshot in the adjacent `.assets` directory. Move/copy the project together with this directory. The original PDF can then be closed or moved without removing the saved production input.
6. Open a generated PDF to return to PDF Workspace. **Back to Designer** retains the originating project; **Open original source page** traces an unchanged overlay output to its original source page. Inserted blank backs have no source page. Editing an output marks its original production QC as stale. Changed source revisions block page tracing until the source is reviewed rather than navigating to a possibly incorrect page.
7. A reopened project retains its snapshot. Reconnecting the original PDF does not replace the snapshot; use **Update source** after the PDF finishes opening.

## Architecture and persistence

- `composition/handoff.py`: headless immutable snapshot capture, revision checks, selected-page capture, background import and provenance validation. Composition remains independent of Qt.
- `ui/workspace_handoff.py`: command-bar entry, lazy project creation, source-link lifecycle, manual updates, output return, source-page tracing and cancellation cleanup.
- `ui/workspace_mode_controller.py`: service ownership, mode routing and command-palette entry. `core/viewer.py` only adds the Normal Search handoff route.
- Existing snapshot/background import, task infrastructure, renderer, overlay planner and project serializers are reused. No new dependency or public version change.
- Template schema is **8**; overlay schema is **4**. Earlier supported schemas still load. Older application builds cannot interpret the new linked-source format. Existing migration tests were updated to assert these intentional version changes; coverage was retained.
- Source metadata includes captured revision identity in memory and persistent transfer ID, digest, page mapping, original path, selection mode and timestamp. Overlay page reports append **Original PDF page**; job logs include source metadata. Source data/passwords are not embedded in metadata.
- Snapshot/assets writes use the existing atomic helpers; source assets are digest-checked before saving. Prior runtime snapshots remain available for source-update Undo and are cleaned after project close and worker cleanup.

## Boundaries

- Capture runs in the existing background-task system. Existing global PDF engine locking requires temporarily disabling PDF editing controls during capture; mode switching and other Designer work remain available. Native PDF save calls are cancellable only at safe checkpoints. Exit is blocked while capture is active; cancel or finish capture first.
- Overlay input keeps the existing uniform page-size/rotation restriction. Signed/signature-field PDFs are rejected for review. Template background import uses the existing annotation/widget flattening path. Unapplied form drafts have an explicit Apply / Send without draft / Cancel decision.
- Geometry changes retain object settings and block production when bounds need repair. Missing page scopes can be explicitly changed for review; no silent repositioning.
- Cross-file Deep Search handoff, automatic synchronization, restart restoration and automatic resume are outside this update.

## Focused verification

- Combined targeted run: **62 passed**, including headless capture, schema migration, existing mode switching, asset persistence, unsaved edits, selection provenance, source update/cancel/Undo, dynamic grouping invalidation, output/QC/page tracing, cancellation and narrow-window light/dark cases.
- Additional source reconnection and template-background update/Undo: **2 passed**.
- Fresh-process **200% scaling** run: **6 passed** (narrow-window theme cases, source-update zoom retention and production-output return).
- Repeated synthetic 3,000-page handoff: **0.656 seconds**, four GUI timer callbacks during transfer. This is a local synthetic fixture result, not a throughput guarantee for image-heavy or network PDFs.
- Ruff passed on new implementation and tests. Isolated 960×640 window snapshots inspected; user’s running application was preserved.
- An exploratory existing `test_rulers_measurement_zoom_pan_and_layout_menu` failed its horizontal-scroll assertion with the offscreen default font. Its setup still tries to select the now-right-hand Properties inspector through the left tab widget. It was not disabled or changed as part of this handoff update; standalone inspector/font layout verification remains a separate known test issue.
- Complete regression and Windows installer/build verification remain deferred as requested.
