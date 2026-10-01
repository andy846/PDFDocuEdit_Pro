# PDF Overlay P0 implementation note — 2026-10-02

Existing composition creates fixed template pages; overlay needs an independent PDF page source.
Keep Template schema 6 and ProductionJob unchanged during the first milestones. Introduce a
versioned, readable .pdcx envelope project with project_kind=pdf_overlay and overlay_version=1.
The Designer open hook will dispatch this discriminator; existing templates continue to open
normally. This replaces the proposed global schema-7 migration and limits compatibility risk.

Use an independent EnvelopeSpec/OverlayJob and lazy PagePlan. Stream a hash-checked source
snapshot into staging, inspect fixed-role geometry, reject unsupported forms/signatures/encryption.
Copy original pages with insert_pdf; place a separately rendered overlay PDF Form XObject over
the copied page. Source fonts and content streams are not subsetted or rasterized. Share the
existing Renderer element painter, font selectors/subsets and Code128/QR implementation.
Only subset new overlay font resources. Probe rotated/cropped placement and pixel preservation
before committing the renderer. Preserve printable annotation appearances through page copying;
interactive links/bookmarks are not a print-production preservation guarantee.

Share existing qpdf assembly, validation, cancellation and job identity helpers. Add exact
per-mark crop decoding with the already bundled pyzbar; no dependency additions. Reports stream
to disk. Machine profiles remain Generic / machine validation pending until actual equipment
specification and physical tests are supplied. Duplex inserts explicit blank backs for odd groups.

Milestones: P1 models/source/planning tests; P2 headless renderer/generator/QC/reports and 3000-page
acceptance; P3 Designer integration; P4 failure/cancel/restore robustness; P5 regression/frozen
benchmarks. Hardware acceptance remains an explicit outstanding gate.
