# Rotated eraser / annotation bounds

## Confirmed defect

The canvas maps visual selection rectangles back to unrotated, CropBox-relative
PDF coordinates. Annotation validation and move/resize clipping used the rotated
`page.rect` for most annotation kinds. On non-square pages rotated 90 or 270
degrees, legitimate selections near a page edge were clipped against swapped
width/height limits.

Both paths also normalized the intersection after clipping. A disjoint
intersection could consequently become a nonempty rectangle in a different
location, rather than being rejected.

## Correction

- `core/annotations.py::validate_annotation_op`: clip every rectangle-based
  annotation against `page.rect * page.derotation_matrix`, as already used for
  image placement.
- `core/annotations.py::update_annotation_geometry`: use the same coordinate
  contract when moving or resizing an annotation.
- Normalize the requested drag before intersection; never normalize the empty
  intersection back into a selectable area.
- Preserve canvas coordinate conversion, PDF rotation, page boxes, transaction,
  redaction processing and save policies.

## Verification (2026-10-18)

- Reproduction before the correction: 18 failures / 14 passes in the new focused
  suite. Failures include wrong edge coordinates and incorrect outside-page
  acceptance.
- Seven affected regression modules: **151 passed, 0 failed, 0 errors, 0 skipped**.
  Includes four real Qt mouse-drag cases at 90/270 degrees and 50%/200% zoom,
  applying redactions, Undo/Redo and saving/reopening a new PDF.
- Geometry fixtures cover 0/90/180/270 degrees, portrait/landscape pages,
  nonzero CropBox offsets, four corners, 50%/100%/200% zoom, partial clipping,
  reverse drags, rejected outside rectangles and existing annotation movement.
- Supplied five-page PDF: 20 in-memory page/rotation scenarios, 80 corner checks,
  rendered mark alignment, actual redaction and reopen passed. Original SHA256
  unchanged. Customer content is not included in repository test fixtures.
- Targeted Ruff and Git whitespace checks passed.

Local evidence: `build/probes/rotated-eraser/` (not committed). Windows/PyQt6
Offscreen automation; interactive owner testing and macOS testing remain
separate. This change does not package, publish or change the product version.
