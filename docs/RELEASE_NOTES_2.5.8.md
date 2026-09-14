# PDFDocuEdit Pro v2.5.8

## New features

- Fill existing AcroForm fields, including text, checkboxes, radio groups and choice lists. Preview values and common calculations before applying them as one Undo step.
- Add image or handwritten signature appearances without creating a digital signature. XFA is not supported; unsupported scripts require explicit acknowledgement.
- Compare private snapshots of PDFs side by side, including unsaved changes. Review text and visual differences, inserted/deleted pages, manual pairing, cancellation and stale-result notices.
- Customize application shortcuts with stable command IDs, dialog/viewer scopes and multi-stroke prefix conflict checks.

## Fixes

- Dependent form calculations no longer consume stale results from unsupported scripts.
- Correct radio export states, clearable text and multi-select values, Unicode appearances, and duplicate-widget synchronization.
- Keep form preview, calculated values, reset, Apply and Undo/Redo consistent.
- Allow manual comparison pairing across unpaired pages without losing pages.
- Release failed rendering jobs from pending state; record contextual diagnostics and handle worker interruptions.
- Validate managed-launcher installations and report missing/failed launchers clearly.
- Preserve existing Organizer, page navigation, centering and signed update behavior.

## Windows packages

- Existing managed installations: use Help → Check for Updates or the signed Update ZIP through the managed updater.
- First installation: extract the entire Managed Portable ZIP into an approved writable location and run Launcher.exe.
- Do not extract a deployment ZIP over an existing managed installation.

The repository remains private. The current anonymous updater cannot access private GitHub Releases; this release does not change repository visibility or add credentials to the application.
