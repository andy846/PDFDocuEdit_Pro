# Undo/redo reliability follow-up

Date: 2026-09-07. Source metadata remains V2.5.4. This completes the first follow-up to the page mutation transaction checkpoint.

## Behaviour

Undo and redo now stage a snapshot of the current in-memory PDF before changing either history stack. The target remains owned by its original stack throughout preparation and installation. A new engine opens and reads the target's page geometry before any live reader is changed. It inherits the current document's save destination, identity and encryption policy, with the target snapshot's modified flag.

The viewer retains the previous engine until the replacement and its view state are installed. An installation failure restores the previous engine and canvas bindings. Only a successful callback allows `UndoStack.restore()` to move the target entry and commit the inverse snapshot. Failed writes, missing/corrupt targets, open failures and display failures preserve the current PDF and both stacks. Temporary inverse files are cleaned after failed attempts. Successful consumption deletes only the consumed target snapshot.

Primary and same-document split canvases, plus other tabs comparing this document, participate in engine replacement. Existing view-state preservation and session undo-recorder binding remain in use. History operations are rejected while print/background work is active. Empty stacks do not create inverse entries.

History jumps stop on the first failed step. Earlier successful steps in that jump remain applied; the jump is a sequence of safe individual moves, not a single multi-step transaction. Reentrant history mutations are rejected while a restore is active.

## Implementation

- `core/undo.py`: staged `restore()` API, history ownership and reentrancy guards. Legacy push/pop APIs retain compatibility for existing callers.
- `core/viewer.py`: shared undo/redo orchestration, prepare/install/recover flow and failure-aware history jumps. Engine replacement can defer closing the previous engine.
- `tests/test_undo_history.py`: both directions, storage/callback failures, unchanged stacks, temporary cleanup, single commit notification and reentrancy rejection.
- `tests/test_ui_smoke.py`: both directions, failed writes, missing/corrupt snapshots, engine-open failure and display failure after replacement; original engine/content/history and split bindings survive, followed by a successful retry.

## Validation

Focused history, UI and transaction group: **39 passed in 11.01 seconds**. Ruff, source verification and git diff whitespace checks passed. **Full suite: 359 passed in 164.65 seconds across 32 modules**, Windows Python 3.12.14; zero failures/errors.

## Remaining work

Annotation and watermark mutations still need migration to the common transaction boundary. Legacy direct stack push/pop APIs remain non-transactional; the viewer's undo/redo paths no longer use them. History snapshots remain temporary local files and are not persistent crash-recovery storage. Further viewer decomposition, shared atomic IO, platform validation and packaging remain separate steps.
