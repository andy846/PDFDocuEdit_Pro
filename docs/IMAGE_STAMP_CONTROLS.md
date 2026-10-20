# Image proportions and image / stamp angles

Implemented directly on the canonical D-drive `main`, starting from `6c13bce`.
Work began 2026-10-20; final verification continued 2026-10-21 (Hong Kong).

## User behavior

- **Insert Image / Signature Image — Create:** Keep proportions controls the
  actual initial placement. Disabled means the image fills the drawn rectangle.
- **Selected image — Manage:** changing Keep proportions immediately changes
  the next corner drag, without Apply. The policy is undoable and persists in
  the PDF. Unapplied width/height/angle inputs survive the checkbox change.
- **Image and Rubber Stamp — Create:** Rotation accepts -360° through 360°,
  including tenths of a degree; default 0°. Positive follows the existing
  watermark convention (counterclockwise). Defaults remain per tool.
- **Selected image / native stamp:** use Manage, or right-click Edit Properties,
  change Rotation and press Apply Position & Size. Watermark editing retains its
  own existing dialog and uniform-scale rules.
- Image selection outlines and corner handles follow the actual image angle.
  With proportions enabled they scale together; unchecked, or with Shift held,
  width and height can change independently without skewing or changing angle.
- Image width/height are measured along its own axes **before rotation**.
  X/Y identify the bounds on the unrotated PDF page. Size edits retain X/Y;
  changing angle retains the centre. An out-of-page rotation is rejected with
  a message, leaving the existing mutation transaction to restore the document.

The reported checkbox defect was a UI/source synchronization issue: the old
checkbox was committed only by Apply, so dragging used the previous stored policy.
The PDF image service already supported free scaling at zero / quarter turns.

## Implementation and safety

| File | Purpose |
|---|---|
| `core/annotations.py` | Optional rotation/proportions request fields, validation before PDF mutation, routing for selected object dimensions/angle |
| `core/page_images.py` | Actual insertion policy; native image-axis sizes/quads; rotation and local-axis resizing; decimal PDF operands; copy-on-write placement streams and integrity hashes |
| New `core/stamp_geometry.py` | Fractional native stamp appearance rotation; copies both the Form and appearance dictionary before editing; preserves vector content and shared sibling appearances |
| `core/viewer.py` | Route dimensions/angle through existing mutation / Undo / refresh paths; retain creation defaults |
| `ui/context_panel.py` | Create/Manage controls, immediate policy update, preservation of pending inputs and precise dimensions |
| `ui/pdf_canvas.py`, `ui/page_overlay.py` | Requests, angled insertion guides, local-axis corner projection and rotated selection handles |
| New `tests/test_image_stamp_controls.py` | Output pixel references, policy/Undo, actual mouse drags, crop/rotation, persistence and ownership regressions |

Image rotation changes only its placement matrix, not image bytes or resolution.
Native stamp appearance text remains vector content. Legacy app-added images
remain editable with their original metadata. Arbitrary affine editing is allowed
only for the application's intact hashed placement stream; untrusted externally
changed streams remain protected. Nonuniform bounding-box-only requests for a
slanted image are rejected; the interactive UI supplies local dimensions instead.

Review found two defects during development and both were reproduced and fixed:
an indirect shared `/AP` dictionary could affect sibling stamps, and scaling a
slanted image's bounding box could shear it and change its angle. A second focused
review confirmed both fixes and found no further Important issue in those paths.

No new dependencies, PDF engine replacement, public version change, production
rule change, branch, worktree, remote push, installer or release is part of this work.
The owner's untracked `BOCHK.pdmp` remains untouched.

## Verification evidence

Local evidence: `build/probes/image-stamp-20261020/` (not committed).

- New controls regression: 38 cases, including independent actual-pixel references,
  native and custom stamps, 0/90/180/270° pages, cropped pages, proportional/free
  mouse drags, shared indirect stamp appearances and invalid-angle rejection.
- `final-regression/`: 22 complete affected modules in fresh Qt processes,
  **644 passed, 0 failed/errors/skipped**. The final pending-input assertion
  was then rerun in all 38 controls cases at standard scaling (all passed).
  Per-module JUnit/logs and `result.json` retain exact counts and status.
- `dpi-isolated-final/`: both image/stamp controls and existing image tests at
  200% Qt scaling, **60 passed**. Standard and DPI modules are isolated by the existing
  project runner because QApplication styles/handles must not leak between modules.
- `visual/result.json`, `visual/light.png`, `visual/dark.png`: isolated settings,
  synthetic output, Undo/Redo, saved editable angles and image proportions.
- Changed-file Ruff and `git diff --check` are required before checkpointing.

Initial failing runs and review reproductions remain available; they were not
deleted or converted to skips. Combined-process experiments exposed the existing
Qt style isolation requirement. A high-DPI screenshot assertion was corrected to
sample physical pixels using its device pixel ratio.

This patch does not repeat the previous whole-project regression as a new claim.
Unrelated production modules are covered by their earlier baseline evidence.
macOS, physical monitor DPI transitions, production printers and a new frozen
release bundle are **Not Tested** for this patch. No unsupported speed claim is made.

## Manual UAT

1. Restart the D-drive development app after saving your current work.
2. Insert an asymmetric PNG/JPEG into a square with Keep proportions both on and
   off. Select it, uncheck the option and drag a corner without pressing Apply.
3. Enter e.g. 27.5° for an image and -12.5° for native/custom stamps. Adjust each
   after insertion. With the image slanted, resize width only; angle and local
   height must stay unchanged. Try proportional corner dragging and Shift.
4. Repeat on rotated/cropped pages. Save/Reopen, Undo/Redo, move and delete one
   object; check other images/stamps and original page content remain intact.
