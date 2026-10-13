# PDFDocuEdit Pro v3.0.6

## Document integrity

- Save and Save As remain available after transaction rollback and Undo restore a PDF from memory; existing full-save/encryption rules are retained.
- Repeated page insertion and scale-copy are one transaction, including direct engine calls. A failed insertion restores the previous document; a successful operation creates one logical revision/Undo entry.

## Production approval and recovery

- Template, Overlay, PDF Workflow, Batch and Branch publication require authenticated Production Review evidence bound to settings, inputs, prepared data, selected work and output destination.
- Restarting, changing settings/resources, or retrying unfinished work requires renewed review. Approval is valid for new starts within the current session and 24 hours; started work is not interrupted by expiry.
- Branch/job identities and destinations are validated; traversal, Windows reserved device names and symlink/junction escapes are rejected.
- Production journals, OS-held job claims and completion manifests cover PDF, PS, JDF, split output and reports. Verified committed output is retained and skipped; incomplete or changed output is not overwritten automatically.
- Visual Workflow > Production > **Recover previous run…** verifies a previous batch folder and retains completed output. Unfinished jobs require Check & Review and an explicit new attempt/destination.
- Post-publication notification/report/state failures are distinguished from failed composition. No silent retry-folder substitution remains.
- Zero selected records produce an approved report-only package, not an empty PDF. Headless callers must supply `ProductionAuthorization` through the documented explicit review contract.

## PDF Workspace and UI

- Right-click an open PDF tab to split with another open document or move it to a separate live document window; editing and Undo remain owned by the original document session.
- Overlay PDF output respects the selected template/target paper-size policy.
- Restored branded sidebar expand/collapse control, distinct color category/tool icons, and matching top/sidebar colors.
- Fixed the first Check of a new Branch Workflow recipe; empty drafts are not mistaken for prior production records.

## Platforms and updates

Windows x64: account-enabled Managed installer/portable. macOS 13+ Apple Silicon:
account-enabled Managed DMG **testing build**, ad-hoc signed and **not Apple notarized**.
Intel, Mac OCR and real printer/DFE acceptance are outside this release.

The three signed update routes remain available, including the original Windows
v3.0.3 Managed Launcher route. Templates/workflows/Overlay/barcode formats and the
update trust key are unchanged. Account login/offline approval and update confirmation
continue to use the existing platform services.

## Validation status

Candidate preparation is in progress. Complete native CI, packaging, signed attachment
verification and candidate operator checks are required by `UNIFIED_RELEASE.md`.
The prior development gate passed 2,365 tests (three native macOS cases unavailable on
Windows); this is not a substitute for this release candidate's native evidence.
Real-printer behavior and large/network-file performance are not claimed from synthetic fixtures.
