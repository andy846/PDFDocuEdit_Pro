# Designer layout and batch editing — 2026-10-03

## M1 — Shared Arrange

Template and overlay workspaces use the same Qt-independent geometry service. Layout and context menus expose selection/page/object references, rotated visible-edge alignment, edge-gap distribution, same dimensions, and explicit gaps in millimetres. Distribution keeps outer anchors. Any invalid result rejects the entire operation before an Undo command is created. Overlay changes affect only currently visible selected objects and preserve their scopes.

Targeted checks: 7 tests covering rotated edges, immutable inputs, references, explicit gaps, invalid operations, both workspaces and one-command Undo. Existing schema retains nonnegative unrotated origins; alignments requiring negative origins are rejected explicitly. No template version or dependency change.

## M2 — Atomic drafts and formatting clipboard

Multi-selection typography and checked dimensions/rotation are staged until Apply changes. Revert changes discards only the pending settings. Mixed controls display Mixed rather than the first object's value. Default typography targets text; Code 128 / I25 human-readable text requires explicit opt-in. Values, rules, profiles, scopes and glyph repairs remain intact.

Exact font export and PDF font checks run in existing background processes before one commit. Failed geometry or font preparation keeps the model and draft intact. Selection, page/preview navigation, save, generation and close resolve Apply / Discard / Cancel. Cancelled application exit preserves drafts in earlier tabs, including deferred Discard requests.

Copy/Paste text formatting uses a session-owned font snapshot with existing embedding permissions and exact-face export. Paste confirms the target count and copies assets into target ownership; closing the source cannot invalidate them.

49 related tests passed (including 23 existing bulk typography tests updated to require explicit Apply, layout geometry tests, exact Windows fonts, source-close clipboard lifetime, save/load, failed font preparation and exit cancellation). Invalid-draft test cleanup now explicitly reverts drafts. Test changes reflect the approved interaction changes, not reduced gates. Ruff passes.
