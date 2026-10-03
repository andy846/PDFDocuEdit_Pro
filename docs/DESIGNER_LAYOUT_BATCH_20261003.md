# Designer layout and batch editing — 2026-10-03

## M1 — Shared Arrange

Template and overlay workspaces use the same Qt-independent geometry service. Layout and context menus expose selection/page/object references, rotated visible-edge alignment, edge-gap distribution, same dimensions, and explicit gaps in millimetres. Distribution keeps outer anchors. Any invalid result rejects the entire operation before an Undo command is created. Overlay changes affect only currently visible selected objects and preserve their scopes.

Targeted checks: 7 tests covering rotated edges, immutable inputs, references, explicit gaps, invalid operations, both workspaces and one-command Undo. Existing schema retains nonnegative unrotated origins; alignments requiring negative origins are rejected explicitly. No template version or dependency change.
