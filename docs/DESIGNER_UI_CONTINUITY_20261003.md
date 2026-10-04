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

## Follow-up — restore the independent right inspector

The earlier narrow-window Properties-tab arrangement is superseded. The
operator expects Textbox parameters to stay on the right, so Design now keeps
Data fields/Layers on the left and the inspector on the right at every width.

- Resizing no longer reparents the inspector into the left tab widget. Its
  splitter position is always index 2, and it cannot collapse to zero width.
  Selection and the Properties toolbar button reveal that same right panel.
  Preview remains a review view; Properties returns to Design for editing.
- Sidebar minimum width follows the actual import/sequence button requirements
  and allows scrollbar space. Preset pane widths are applied on entering a
  narrow/wide band, while user adjustments within a band remain intact.
- Inspector controls use less vertical padding. Typography and content precede
  the less frequent Object rules group. Wrapped titles and a width-independent
  barcode selector prevent unnecessary horizontal overflow.
- A shared `InspectorScrollArea` reveals complete widget bounds. Native Qt
  `ensureWidgetVisible` used the text editor's focus proxy in the reproduced
  case and left 16 pixels of the outer control below the viewport. Template and
  overlay now use the full-control calculation.
- Four integrated main-window tests passed for 760×580/960×640, light/dark,
  fixed right position, full parameter reachability, zero horizontal inspector
  scroll, mode switching and preventing accidental collapse. The eight sidebar
  cases passed alongside these four (**12 passed**).
- Other focused continuity/usability/compact checks: **43 passed**. At 200%
  scale the four integrated and eight sidebar cases passed (**12 passed**).
  Ruff and whitespace checks passed. No full regression or packaging run.
- The old left-tab inspector assertions were replaced with right-panel
  assertions intentionally; resize, Preview, View toggle and saved-layout
  preservation checks remain.
- Integrated screenshots with loaded Windows Segoe UI fonts were reviewed.
  The isolated layout audit also exercised 640×400 and 1280×820 with generated
  quantity 100,000, without starting a production job. QA screenshots and
  scripts remain ignored under `build/designer-continuity-qa/`.

The desktop capture helper failed to initialize twice; the operator's live
window could not be captured. Validation used isolated application instances
and synthetic data. An existing operator instance is not forcibly restarted.

## Follow-up — screen-aware canvas resolution

The template and PDF-overlay preview workers previously always rasterized at
1.5 PDF pixels per point (108 DPI), irrespective of canvas zoom or display
scale. The canvas also used the fast pixmap transformation mode, which degraded
text when the image was enlarged or reduced.

- Both workers now accept the canvas raster scale. It follows zoom and the
  viewport device pixel ratio, with 25% oversampling and reusable quality bands.
  Zoom changes within a band and ordinary geometry synchronization do not
  request duplicate quality updates. Display-DPI changes request new pixels.
- Quality refreshes use the existing debounced, latest-request-only background
  preview queue. The existing image stays visible until its replacement is
  ready. Scene, object selection, transforms and Undo state remain intact.
- Canvas geometry, ruler text and pixmap scaling use antialiasing/smooth
  transformation. This changes preview display, not production PDF rendering.
- The headless raster helper independently validates finite positive inputs
  and caps a page at 16 million pixels / 8192 pixels per edge before native
  rendering. Custom page sizes and extreme zoom cannot request unbounded full
  page images. Extreme zoom is limited by this raster budget; viewport tiles
  are not implemented in this change. This is not a cap on total process RAM.
- At 200% canvas zoom on a normal-DPI display, the same A4 preview increased
  from 893 x 1263 (108 DPI) to 2382 x 3368 (288 DPI). Before/after screenshots
  were reviewed for 6/8-point text, thin lines and Code 128. At 200% display
  scale, larger previews are requested automatically, within the page budget.
- Focused headless/raster and canvas-continuity tests: 39 passed; an additional
  native allocation-budget case passed (40 distinct checks). Three quality and
  real-worker refresh cases also passed in a fresh 200% display-scale process.
  Checks include both template/overlay workers, vector PDF text/page geometry,
  invalid raster input, large custom pages, DPI changes, latest zoom selection,
  selection/Undo retention and temporary-file cleanup. Ruff/whitespace passed.
- Old preview requests without a raster scale remain supported with a 2x
  default. No dependency, public version, template schema or project migration
  changed. Full regression and Windows packaging remain deferred.

Visual artifacts are ignored under `build/designer-continuity-qa/`:
`designer-resolution-before.png` and `designer-resolution-after.png`.
