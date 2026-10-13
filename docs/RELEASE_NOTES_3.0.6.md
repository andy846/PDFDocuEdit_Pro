# PDFDocuEdit Pro v3.0.6

## Document integrity

- Save and Save As remain available after transaction rollback and Undo restore a PDF from memory; existing full-save/encryption rules are retained.
- Repeated page insertion and scale-copy are one transaction, including direct engine calls. A failed insertion restores the previous document; a successful operation creates one logical revision/Undo entry.

## Production approval and recovery

- Template, Overlay, PDF Workflow, Batch and Branch publication require authenticated Production Review evidence bound to settings, inputs, prepared data, selected work and output destination.
- Restarting, changing settings/resources, or retrying unfinished work requires renewed review. Approval is valid for new starts within the current session and 24 hours; started work is not interrupted by expiry.
- Branch/job identities and physical destinations are bound to approval; traversal, Windows reserved device names, directory junctions and report-file symlinks are rejected before writes. PDF Workflow uses the authenticated extraction database, not a replacement request reference.
- Production journals, OS-held job claims and completion manifests cover PDF, PS, JDF, split output and reports. Split jobs claim their final destination before rendering, so verified committed work is skipped without recomposition. Recovery also checks the original published branch/template binding; missing or changed proof requires review. Incomplete or changed output is not overwritten automatically.
- Visual Workflow > Production > **Recover previous run…** verifies a previous batch folder and retains completed output. Unfinished jobs require Check & Review and an explicit new attempt/destination.
- Post-publication notification/report/state failures are distinguished from failed composition. No silent retry-folder substitution remains.
- Zero selected records produce an approved report-only package, not an empty PDF. Headless callers must supply `ProductionAuthorization` through the documented explicit review contract.

## PDF Workspace and UI

- Right-click an open PDF tab to split with another open document or move it to a separate live document window; editing and Undo remain owned by the original document session.
- Overlay PDF output respects the selected template/target paper-size policy.
- Restored branded sidebar expand/collapse control, distinct color category/tool icons, and matching top/sidebar colors.
- Fixed the first Check of a new Branch Workflow recipe; empty drafts are not mistaken for prior production records.
- PDF windows reuse the current application stylesheet; theme changes synchronize once. Closed secondary windows release their Qt widgets after background readers/tasks finish, avoiding cumulative theme refresh stalls.

## Platforms and updates

Windows x64: account-enabled Managed installer/portable. macOS 13+ Apple Silicon:
account-enabled Managed DMG **testing build**, ad-hoc signed and **not Apple notarized**.
Intel, Mac OCR and real printer/DFE acceptance are outside this release.

The three signed update routes remain available, including the original Windows
v3.0.3 Managed Launcher route. Templates/workflows/Overlay/barcode formats and the
update trust key are unchanged. Account login/offline approval and update confirmation
continue to use the existing platform services.

## Validation status

Native candidate verification passed on source `a7bea706311b8542888c46f877ce65be63efb467`:
Windows: 170 modules, 2,378 passed / 3 platform skips. macOS: 40 modules, 642 passed / 3 platform skips.
Both native account packages, Managed startup and unauthenticated worker admission checks passed.
All three update routes and the signed attachment index were verified. Candidate operator login,
offline restart and cross-version update acceptance remain pending.

### Owner-directed publication

Published at the owner's explicit request after disclosure of the four outstanding candidate operator checks: Windows real-account login; macOS real-account login, offline restart and cross-version update. These remain Pending and are not represented as passed. This decision applies only to v3.0.6 and this frozen source; the normal release gates remain unchanged.
Real-printer behavior and large/network-file performance are not claimed from synthetic fixtures.
