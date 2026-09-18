# PDFDocuEdit Pro v2.5.11

Bug-fix release for Advanced Page Organizer regressions introduced in v2.5.10.

## Fixes

- Restore mouse drag reordering in the large-document Organizer, including selected groups and plan Undo / Redo.
- Show the insertion position while dragging; scroll at viewport edges and allow Esc to cancel.
- Restore rounded thumbnail cards, themed selection fills and selection badges. Remove the square outer frame and fix Windows accent-color rendering.
- Preserve virtualized page items, background preparation and bounded, visible-first thumbnail rendering.

## Updating on Windows

Existing Managed Portable users: start Launcher.exe, then use Help > Check for Updates.
For a fresh deployment, extract the complete Managed Portable ZIP to a writable folder and run Launcher.exe.
Do not extract a Managed Portable ZIP over an existing managed installation.

The Update ZIP, update.json and update.sig are signed update artifacts. Matching SHA-256 files accompany both ZIP packages.

## Validation

Organizer regressions cover real Qt mouse press/move/release input on a synthetic 18,000-page document, multi-page ordering, Undo / Redo, edge scrolling, cancellation and rounded theme rendering. Both light and dark appearances were visually checked.
