# Document Designer — layout and mailpiece review hardening

2026-10-03. Development worktree only; existing public version and release packaging remain unchanged.

## Functional fixes

- Reinspection and sequence/grouping changes retain the pending mailpiece review requirement. They cannot turn an unaccepted dynamic project into an immediately executable fixed grouping project. Uniform source geometry inspection is retained.
- Cached review windows are refreshed when project grouping/review state changes, including project Undo, rather than applying stale cached boundaries.
- Source-page previews run at most one worker per review controller, with only the latest queued page retained. Superseded non-publishing previews are stopped. UUID output names prevent collisions between review windows. Stale success/error callbacks cannot replace the latest page or its details; completion/close cleans preview images.
- Closing/reopening a review ignores a cancelled scan's late result. The production worker continues to use its existing cooperative cancellation and output validation.
- Rotated resize preserves the opposite (top-left) corner as width/height change. It remains one canvas edit and one project Undo action.
- Edited overlay geometry and page scopes are checked against applicable source-page sizes at commit time, using the same headless bound check as the output renderer. Fixed layouts check page roles, not every envelope. Existing invalid projects still open for repair.
- Rejected overlay drags/resizes restore the visible canvas as well as keeping the saved model unchanged.
- Invalid numeric geometry changes are rejected atomically and the controls return to the selected objects' actual dimensions. Mixed dimensions are labelled; unchecked properties remain unchanged.
- A full-page region rounded to two decimal millimetres is clipped within a small 0.03-point rounding tolerance; real out-of-page regions still fail.
- Literal ID patterns with suffixes stop at the first suffix. Printed-page numbers cannot be partially matched inside a longer digit sequence. Unexpected rule options are rejected. Blank marker lines in the UI are ignored.

## Operator convenience

- A vertical splitter lets operators allocate space between the boundary list and PDF preview.
- Source page loading/current-page indicators avoid mistaking an old preview for a newly selected page; region dragging waits for the requested image.
- Manual region coordinates are drawn on the preview and survive page changes. Ctrl+wheel zoom is bounded; manual zoom survives window/pane resizing. Space temporarily enables panning; Fit page restores automatic fitting. Reloading an image during a drag safely resets interaction state.
- Next warning cycles through warning pages, including warnings on excluded separators.
- Split/merge keeps focus at the edited boundary. Local Undo edit / Redo edit retains up to 20 boundary edits; it stores boundaries/edit history without copying all scan evidence into each history entry. Acceptance must be checked again after changes. Main project state changes only with Accept & apply, which remains one project Undo action.
- Changed detection options clear old rows, warning details and review history and require another scan. Scan progress is visible inside the review window and uses a slim text-free bar plus a readable status label.
- Enter does not implicitly activate the Scan/Accept footer buttons. Selected table rows use the theme's matching highlight/background text colours.

## Verification scope

Only affected tests are executed, as requested. Full application regression, large release benchmarks and Windows packaging remain deferred.

Normal-scale focused verification: **79 cases passed** (77 combined cases and two final page-bound/recovery cases; the latter also exercised alongside the combined suite). layout/rotation, mailpiece detection and new hardening cases, plus shared bulk typography. Coverage includes actual PDF generation and Code 128/I25/QR decoding, preview/output agreement, dynamic duplex pagination/reconciliation, source identity, background QProcess scanning, review application/Undo, atomic geometry rejection and rotated dragging.

200%-scale focused run: **16 passed**. the hardening cases plus narrow review controls, real background scan/review and main mode controls in both themes. Windows Segoe UI was explicitly loaded for visual inspection at 960 × 640; both themes showed zero horizontal scrolling in the configuration panel and all action buttons inside the window. Ready-state preview height increased from 142 to 178 logical pixels with the default layout; the divider can increase it further. Scan-state layout was also inspected.

The customer `merged.pdf` has not been regenerated or rescanned in this hardening pass. Earlier grouping candidates still require operator confirmation. Text-layer and homogeneous page-geometry limits continue to apply. This checkpoint does not claim inserter hardware certification or full release readiness.

## Try the changes

Save current projects and reopen the development build. In PDF overlay, open **Detect mailpieces**, select a method and scan. Use **Next warning**, **Split here**, **Merge with previous**, **Undo edit / Redo edit**; drag the list/preview divider as needed. Accept boundaries after checking the results. In either designer, select multiple objects and edit checked width/height/angle settings in **Geometry**.
