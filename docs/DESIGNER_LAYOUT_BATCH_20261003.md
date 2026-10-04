# Designer layout and batch editing — 2026-10-03

## M1 — Shared Arrange

Template and overlay workspaces use the same Qt-independent geometry service. Layout and context menus expose selection/page/object references, rotated visible-edge alignment, edge-gap distribution, same dimensions, and explicit gaps in millimetres. Distribution keeps outer anchors. Any invalid result rejects the entire operation before an Undo command is created. Overlay changes affect only currently visible selected objects and preserve their scopes.

Targeted checks: 7 tests covering rotated edges, immutable inputs, references, explicit gaps, invalid operations, both workspaces and one-command Undo. Existing schema retains nonnegative unrotated origins; alignments requiring negative origins are rejected explicitly. No template version or dependency change.

## M2 — Atomic drafts and formatting clipboard

Multi-selection typography and checked dimensions/rotation are staged until Apply changes. Revert changes discards only the pending settings. Mixed controls display Mixed rather than the first object's value. Default typography targets text; Code 128 / I25 human-readable text requires explicit opt-in. Values, rules, profiles, scopes and glyph repairs remain intact.

Exact font export and PDF font checks run in existing background processes before one commit. Failed geometry or font preparation keeps the model and draft intact. Selection, page/preview navigation, save, generation and close resolve Apply / Discard / Cancel. Cancelled application exit preserves drafts in earlier tabs, including deferred Discard requests.

Copy/Paste text formatting uses a session-owned font snapshot with existing embedding permissions and exact-face export. Paste confirms the target count and copies assets into target ownership; closing the source cannot invalidate them.

49 related tests passed (including 23 existing bulk typography tests updated to require explicit Apply, layout geometry tests, exact Windows fonts, source-close clipboard lifetime, save/load, failed font preparation and exit cancellation). Invalid-draft test cleanup now explicitly reverts drafts. Test changes reflect the approved interaction changes, not reduced gates. Ruff passes.

## M3 — Selection and viewport polish (completed 2026-10-04)

Both Layers/Objects panels offer an object-type filter and Select type for the current visible page. Canvas/list selection stays synchronized. The inspector and template status show selection and formatting target counts. Layout also exposes Apply/Revert pending settings without scrolling back through properties. Mixed toolbar font sizes no longer display the first object's value.

Batch commits retain exact zoom/pan, selection, layer scroll and the existing preview pixmap. One batch schedules one preview. Fixed the template's one-pixel pan drift caused by centerOn rounding, narrow-overlay auto-hiding of an active inspector, long overlay controls causing horizontal scrolling, Undo availability after Revert, and late font callbacks during shutdown.

Validation: 68 targeted cases passed across the related checks: 58 Arrange/batch/font/selection/layout cases, 9 main-window shortcut/inspector/exit and canvas interaction cases, and 1 late-font shutdown case. This includes a fresh Qt process at devicePixelRatio 2 with both workspaces and both themes at 960×640, licensed real-font clipboard lifetime, actual PDF text output, and preview scheduling counts. A rendered UI review was also inspected. Ruff and git diff --check pass.

Full application regression, Windows packaging and large production benchmarks remain deferred as requested. Existing public version, JSON schema versions and dependencies are unchanged. M1 checkpoint: 8d1c075; M2 checkpoint: 3a25cde; M3 is the commit containing this section.

### Operator entry points

- Layout → Arrange selected objects…: choose operation/reference/gap.
- Select multiple objects → Properties: edit settings, Apply changes or Revert changes.
- Layout / canvas context menu: Copy text formatting / Paste text formatting.
- Layers / Objects: choose type, Select type. Overlay selection applies only to currently visible objects; page scopes and barcode payloads are retained.
