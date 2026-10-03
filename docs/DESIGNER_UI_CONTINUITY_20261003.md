# Document Designer — shared UI and continuous canvas

Date: 2026-10-03
Baseline: `113ddfb` on `feature/print-composition-v3`.

## Changes

- Designer toolbars, project tabs, panel tabs, properties, status bar and rulers
  use the PDF Workspace palette and spacing tokens. Light/dark theme changes
  update the existing canvas and icons without rebuilding the scene.
- Project tabs reuse the PDF Workspace close button, including its click
  tolerance and animation preference. Closing after tab reordering still targets
  the correct project; Cancel preserves unsaved content.
- Both template and PDF overlay canvases retain their scene, page and existing
  element items. Edits synchronize geometry and properties by element ID;
  deleted/new elements are removed/added individually. Selection, pan, zoom and
  Undo/Redo remain available.
- A same-page edit retains the last successful preview while the new page is
  rendered in the background. The ready image replaces the pixmap in place.
  Continuous edits queue only the latest request after the prior preview worker
  has exited; outdated results cannot replace the current image. Preview files
  are cleaned after delivery or worker exit.
- Selection outlines, resize handles, grid and alignment guides use the shared
  primary colour. The native extra black selection border is suppressed.
- PDF overlay has a toolbar toggle for Object properties. Narrow windows may
  initially hide the inspector to give the canvas more room, but reopening it
  survives subsequent resizing within the narrow layout.
- The new canvas tests belong to the CI UI group.

## Preview boundaries

The previous image is deliberately cleared when switching template page,
record/data preview context, source PDF page or project, changing page size or
background, entering an invalid content draft, or receiving a current preview
failure. A failed preview must not appear to be a valid current result.

Rendering still generates the requested page in a background process. This
change removes scene destruction and blank-image transitions; it does not add
incremental per-element PDF rendering. The last raster may show the previous
layout briefly while the updated preview is being prepared, with “Updating
preview…” visible. Composition output, rules, font repairs, project format and
dependencies are unchanged.

## Focused verification

- Existing targeted checks covered Designer controls/usability, layout geometry,
  compact layout, hardening, multipage projects, PDF overlay, workspace modes
  and PDF UI smoke cases. No full application regression or packaging run was
  performed.
- Final focused batch: **28 passed** across canvas continuity, compact layout,
  close/cancel/theme routing and CI planning.
- Real rapid edits with actual background workers: **2 passed**, one template
  and one overlay. Both deliver the latest image, retain the scene items and
  leave no preview temporary files or active workers.
- At `QT_SCALE_FACTOR=2`: **8 passed** for light/dark palette, narrow property
  access, compact controls and reordered project tab close behavior.
- After the last icon adjustment, the shared close-button test was rerun and
  passed, including live theme changes, disabled animations and Cancel/Discard.
- Changed Python files passed Ruff; `git diff --check` passed.
- Offscreen integrated-window screenshots were reviewed with synthetic PDFs
  and CSV data. Both project toolbars measured 37 logical pixels. Screenshots
  are under `build/designer-continuity-qa/` (ignored QA artifacts).

The existing stale-preview error test was updated intentionally: retain the
last valid image while a new render is pending, then clear it if the current
render fails. Its failure assertion remains in place.

## Manual follow-up

Save projects and reopen the application to load these source changes. An
already running application retains its imported code; it was not forcibly
terminated, so operator work is preserved. Test dragging, multi-selection,
resizing, typography edits, Undo/Redo, rapid edits and returning between PDF
Workspace and Designer using a real production template.

Full regression and Windows packaging remain deferred until the operator
confirms this batch of feature changes is complete.

## Follow-up — Textbox inspector discoverability

The narrow layout moved the inspector into the left Properties tab, but ordinary
selection did not activate that tab. A selected object could therefore have
loaded properties which were not visible to the operator.

- A new selection in Design now reveals the inspector automatically. Wide
  windows use the right panel; narrow windows activate the Properties tab.
  Multi-selection uses the same panel. Revealing it does not move keyboard focus
  from the canvas or reset its view/preview.
- The template toolbar includes a Properties action. It opens the inspector
  even if the panel preference was already enabled while another left tab was
  active. In Preview/Data/Production it returns to Design to edit. The label is
  shown from 900 logical pixels; narrower layouts retain the icon and tooltip.
- Inactive Properties pages follow QTabWidget visibility, preventing a hidden
  page from being explicitly shown over Data/Layers during layout updates.
- Selecting an overlay object likewise reopens its hidden inspector without
  stealing canvas focus.
- Focused validation: **51 passed** across continuity, usability, compact layout
  and geometry; **8 passed** at 200% scale. Tests include actual mouse selection,
  hidden-panel recovery, bulk size changes/Undo and returning from Preview.
  Ruff and whitespace checks passed. The integrated screenshot was reviewed.

## Follow-up — field sidebar footer clipping

A narrow-window reproduction allocated 40 pixels to a footer requiring 54,
clipping the instructions beneath the merge/data field list. Long source names
and larger fonts could consume more of the panel without an outer scroll path.

- Template Data fields and overlay source/system fields now use the existing
  scroll container. Content has a layout minimum; limited height produces a
  scrollbar instead of compressed or inaccessible footer content.
- The field list retains usable height and its own scrolling for long field
  collections. Filtering, double-click insertion and drag/drop connections are
  unchanged. The template field list has 84 pixels minimum height; the overlay
  Fields/Objects tab container has 165 pixels minimum height.
- Sidebar buttons use short labels (`Import data…`, `Sequences…`) and compact
  padding. Tooltips retain supported formats and the running-sequence purpose.
- The sidebars share existing Designer palette and border styling.
- **31 distinct focused tests passed**, including both sidebars, 200 fields,
  long source details, 9/14-point UI fonts, light/dark themes, reachable footer
  bounds, existing compact layout and previous inspector/canvas fixes. **8
  sidebar cases passed at 200% scale**. Ruff and whitespace checks passed.
- An integrated narrow-window Data fields screenshot was reviewed at
  `build/designer-continuity-qa/designer-data-fields-narrow.png`.

The operator's running application was retained; save and reopen it to load
the new sidebar layout. Full regression and packaging remain deferred.
