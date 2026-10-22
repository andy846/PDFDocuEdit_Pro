# Native point annotation geometry repair

Date: 2026-10-22. Owner-approved scope: move/resize Highlight, Underline,
StrikeOut, Squiggly, Ink and Polygon, with native geometry and transactional safety.

## Baseline and diagnosis

Development workspace: `D:\Python_Project\PDFdocuEdit_Pro`, local `main`,
`.venv-dev`, Python 3.12 / PyMuPDF 1.26.6. Baseline:
`991b6b34a09fde5a05e637c1cada4e0e10f7a6cc`, public version 3.1.0.
The pre-existing untracked `BOCHK.pdmp` was excluded and not read or changed.

These six native annotation types cannot be moved with `Annot.set_rect()`.
MuPDF reports an unsupported Rect operation without raising a Python exception;
the previous handler returned an xref and the Viewer could record a successful
edit even though the annotation stayed in place. The first 177 targeted tests
failed against that implementation.

## Implementation

- [Core geometry](../core/annotations.py): transform every native point from
  the original annotation rectangle to the requested rectangle. Preserve quad
  ordering, separate Ink strokes, Polygon vertices, xref and annotation metadata.
- Write `/QuadPoints`, `/InkList` or `/Vertices`, plus the native PDF `/Rect`.
  Reuse `_native_matrix()` under `DOCUMENT_LOCK`, temporarily neutralizing page
  rotation for correct CropBox conversion and restoring the original rotation.
- Detach the appearance dictionary and normal stream before `Annot.update()`.
  Shared appearances belonging to other annotations stay unchanged. Normal
  appearance state dictionaries and alternate R/D appearances are explicitly
  rejected before writes; this implementation does not reinterpret those states.
- Read back point counts, coordinates, kind, bounds and appearance ownership.
  Missing, malformed, out-of-page or unverifiable geometry fails explicitly.
  The existing Viewer transaction restores document, readers, history and modified
  state after any mutation failure. No standalone second transaction is added.
- [PageOverlay](../ui/page_overlay.py): clamp whole-object moves within the
  visible page and retain the last valid preview for an out-of-page resize.
  Point annotations do not inherit image aspect-ratio locking. Preview motion
  changes no PDF data; release emits the existing geometry command.
- [Viewer](../core/viewer.py): show the expected annotation validation reason
  through the existing mutation error channel rather than reporting success.
- `list_annotations()` adds optional nested `ink_strokes` for Ink. Its existing
  flat `vertices` remains empty for Ink; interchange schemas are unchanged.

MuPDF preserves fixed border widths and recalculates annotation padding. After
resize, the actual rectangle can differ slightly from the requested rectangle;
selection refresh uses the actual annotation. An appearance extending outside
the visible page is rejected and rolled back, rather than clipped silently.

## Verification

Local evidence: `build/probes/point-geometry-20261022/` (not committed).

| Verification | Result |
|---|---|
| New core tests | 277 passed |
| New Qt / Viewer tests | 65 passed |
| Existing related regression, 15 modules | 356 passed after encoding-correct rerun below |
| Windows isolated PyInstaller QA | 24 synthetic geometry cases at each of DPI 1 and 2, passed |
| Light / dark | Exercised in both frozen QA runs |
| Ruff, whitespace and source verification | Passed |
| macOS / physical printer / inserter / real customer files | Not Tested for this repair |

The new tests cover stable xrefs, styles, multiple skewed quads, separate Ink
strokes, shared direct/indirect appearances, malformed points, unsupported
appearances, missing xrefs, update/readback failure, Undo/Redo, split-reader
rebinding and Save/Reopen. Pixel bounds and serialized output are checked for
all six types at 0/90/180/270 degrees, offset CropBox and 1x/2x rendering,
including nonuniform resizing. Real QTest mouse events cover four rotations
and 75%/150% zoom; no mutation occurs before mouse release.

Initial UI test execution encountered the sandbox's inaccessible default pytest
temporary root. All subsequent tests used the short owned temporary directory
below. A synthetic Highlight Undo comparison initially compared in-memory floats
with serialized PDF precision; the test now compares serialized renders on both
sides, matching the transaction backup format. These were fixture corrections.

Three existing subprocess lifecycle tests initially failed because Python decoded
UTF-8 child stderr as Windows CP950. Their entire module passed unchanged (16/16)
with `PYTHONUTF8=1`. The original failed logs and corrected JUnit are retained;
no product code or test assertions were changed to hide that environment issue.

### Reproduction commands

PowerShell, from the development workspace:

```powershell
$env:TEMP='D:\Python_Project\PDFdocuEdit_Pro\build\probes\pg-tmp'
$env:TMP=$env:TEMP
$env:PYTHONUTF8='1'
.venv-dev/Scripts/python.exe -m pytest -q tests/test_point_annotation_geometry.py tests/test_point_annotation_geometry_ui.py
.venv-dev/Scripts/python.exe -m pytest -q tests/test_error_recovery_lifecycle.py
.venv-dev/Scripts/python.exe -m ruff check core/annotations.py core/viewer.py ui/page_overlay.py scripts/ci_plan.py tests/test_point_annotation_geometry.py tests/test_point_annotation_geometry_ui.py
.venv-dev/Scripts/python.exe scripts/verify_source.py
git diff --check
```

The existing per-module runner was called as `scripts.regression_suite.run()`
using these module paths (each in a fresh process): `test_annotations`,
`test_annotation_transactions`, `test_mutation_transactions`,
`test_rotated_annotation_bounds`, `test_page_overlay`, `test_image_stamp_controls`,
`test_watermark_placements`, `test_watermark_integrity`,
`test_watermark_close_reopen`, `test_document_windows`,
`test_queued_open_lifecycle`, `test_error_recovery_lifecycle`,
`test_session_temp_cleanup`, `test_ci_plan`, `test_source_contract` (all under
`tests/`, with `.py`). Individual commands, JUnit and timings are retained in
the probe's `regression/` directory. This was a targeted regression, not the full
product release suite.

The isolated frozen probe uses synthetic PDFs and app resources. It is not an
installer, a release candidate or evidence of production-device compatibility.
Representative rotated Highlight and Ink PNGs were visually inspected.
One fresh read-only reviewer independently reran 277 core and 65 UI tests,
checked missing-appearance recovery, and reported no critical or important
findings in the approved scope. Arbitrary third-party custom appearance artwork
has not been visually validated; coverage is synthetic native annotations.

## Performance and limitations

Geometry transformation is linear in the selected annotation's point count.
It adds no workers, page scans, font scans, dependencies or redraw-time database
work. Existing document-level transaction snapshots remain the dominant cost
for very large PDFs; no large-document speed claim is made for this repair.

This scope does not change text selection on scanned PDFs, Note properties,
Ink simplification, Callout interchange, redaction UX or numeric geometry panels.
The optional Ink field does not claim to repair Ink import/export.
An additional synthetic review probe found that PyMuPDF 1.26.6 can expose
incorrect native bounds for non-default `/UserUnit` combined with page rotation.
Those unusual PDFs may be rejected by geometry readback; support for them is not
claimed. This does not bypass rollback or turn a failed edit into success.

## Owner UAT

1. Open a disposable PDF; create all six supported annotation types, including
   multiple highlighted lines and multi-stroke Ink.
2. Move and freely resize them at 75%, 100% and 150% zoom. Check the committed
   annotation, not only its drag outline. Try all page rotations and page edges.
3. Undo/Redo, enable split view, save to a new PDF and reopen. Check placement,
   shape, stroke separation, color, opacity and annotation notes.
4. For an annotation with unsupported appearance states, verify a visible error
   and an unchanged document. Do not overwrite a customer original for UAT.

All changes remain on the current local main for owner review. No public version
change, branch/worktree creation, push or release is part of this task.
