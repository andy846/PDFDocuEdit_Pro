# Visual Workflow stability correction — 2026-10-04

## Observed failure

- Windows Application events 1000/1001 at 00:48 report `pythonw.exe`,
  `Qt6Widgets.dll` 6.8.2, access violation `0xc0000005` at offset `0x3ef070`.
- The user recalls clicking the fourth workflow node. The launch stderr contains
  no Python traceback, so the Windows event alone cannot identify the exact
  C++ call that failed.

## Correction

`WorkflowCanvas.display()` previously cleared and rebuilt the graphics scene on
every model commit. A commit can happen synchronously during a node selection
(applying the previous inspector's draft), drag release, or edge double-click.
The scene clear deletes graphics items while Qt is still dispatching their
mouse events.

The canvas now updates surviving nodes/edges in place. Removed items leave the
scene immediately but are deleted after the current event has returned. Scene
signal blocking is restored in a `finally` block. Edge double-click accepts its
event before emitting the deletion request.

No workflow file format, engine, dependencies, or public version was changed.

## Targeted verification

- Existing and added workflow UI checks: **22 cases passed**, using the native
  Windows Qt backend with Python faulthandler enabled. This covers workers,
  region editing, review, mode switching, inspector drafts, graph interactions,
  Undo, and narrow light/dark layouts.
- New checks cover drag after pending settings, edge double-click removal/Undo,
  and 15 consecutive grouping edits followed by a click on the fourth node.
- Running the fourth-node check with the original scene rebuild reproduced lost
  node selection; the original drag check also lost the first drag. Both pass
  with the correction. The original native access violation was not reproduced
  deterministically, so this is a verified correction of a hazardous event
  lifetime path, not proof that every possible Qt crash has been eliminated.
- Ruff and whitespace checks passed. Full regression/build remains deferred per
  the user's request to test only the affected work.

The next test launch uses `-X faulthandler` with redirected stderr to capture a
Python stack if another native crash occurs.
