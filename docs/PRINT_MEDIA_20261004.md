# Print Media / Canon offline ticket — implementation notes

2026-10-04. Development feature under the existing Document Designer flag. No public version change or printer certification.

## Operator workflow

1. Letter Template: **Page → Print Media / Stocks…**. PDF Overlay: **Production → Print Media / Stocks…**.
2. Define stable Stock IDs, display names, dimensions, weight and preprinted status. These are paper identities; the DFE assigns loaded trays.
3. Assign template page identities, logical page numbers, or SINGLE / FIRST / CONTINUATION / LAST roles. Select multiple rows and **Assign selected pages** to apply one Stock. Empty fallback blocks unmatched pages. New letter templates default to stable page identities, so reordering does not move a page's Stock. Duplicating a page copies its identity-based Stock; deleting removes that assignment.
4. Select simplex / duplex. Different Stocks on one physical sheet block generation. Selecting **Insert blank backs at Stock changes** requires explicit confirmation; odd letter endings are padded in duplex mode.
5. Select a Canon reference family (varioPRINT 6300 / 6000, i300, iX), record the actual controller/version notes and map each used Stock to its Media Catalog name and/or ID. Every profile remains **Pending** until physical-device validation is performed outside this development feature.
6. **Check & Preview** shows logical/source pages, final output pages, front/back, sheets per record, Stock and reasons, plus physical stock totals. Rows are paged in windows of 200. Changing options invalidates the check. Preview runs in the existing isolated worker and can be cancelled. Double-click a nonblank row or choose **Show source / template page** to select its Designer/Overlay/checked-job preview page without applying draft settings.
7. Generate normally. Each publishable PDF has an offline `default_ticket.jdf`, `media-plan.csv`, `media-summary.csv`, `media-summary.json` and `job.json` in its package folder. Existing control/font/workflow reports are retained.

Media and printer profiles can be saved/loaded as versioned JSON in the application's settings directory. They contain declarative settings, no customer data values or executable instructions.

## Visual Workflow

**Media Assignment** accepts Record Set or Mailpiece Set. Place it after cleaning/filtering/sorting/validation and before the new Running Sequence / Split Output / Overlay steps. In Mail Merge it can follow Letter Template. The node overrides template media for that job; without the node, saved template settings apply.

Adding the node upgrades the workflow to `.pdflow` version 4. Saved legacy workflows prompt for an upgraded copy; the original remains available. Existing v1–v3 flows remain readable and do not gain media instructions automatically. Templates now save version 10 and overlays version 6; use Save as before reopening with older builds.

PDF workflows preserve the accepted original grouping and source provenance. Filtering and sorting select/order whole envelopes before the physical plan is built. Zero selected records still produce audit reports without an empty PDF.

## Shared physical plan

- `composition/media/model.py`: `MediaSpec`, `PrinterProfile`, strict version/options validation.
- `planner.py`: `PrintPlan`, logical-page identity, physical sheets, inserted blanks, per-Stock counts and `MediaPreflightResult`.
- `ticket.py`: disk-backed page/media audit and reference JDF export/coverage validation.
- `composition/designer/media_dialog.py`: normal forms, batch assignment, profile management, background preview.

The engine has no Qt dependency. Template renderer, font/rule preview, page sequences, overlay fields/barcode payloads, reconciliation and ticket output use the same physical mapping. Template previews navigate logical pages; Media Preview and overlay previews expose physical pages. New `PageRole` and `MediaStock` fields are available in overlays.

Stock transitions add a blank *back* using the front's Stock. The next logical page begins a fresh sheet. Logical FIRST/LAST roles do not change. Output-page sequences count physical pages, including blanks, and retain global values across splits. The existing renderer leaves newly inserted template blank backs unpainted; overlay `all_output` objects may intentionally mark backs, while `all_source` excludes them.

Each output is reopened/page-count checked before publishing its job directory. Reconciliation checks complete source coverage, physical front/back Stock agreement, counts and zero-based JDF range coverage without overlaps or omissions. Failure/cancellation publishes diagnostics, never a production PDF or usable ticket.

## Offline Canon backend and boundaries

JDF 1.3 uses `DigitalPrintingParams` / `MediaRef` partitions with **zero-based RunIndex**, Media `DescriptiveName` / `DeviceProductID`, dimensions and weight. Consecutive ranges are compacted; attributes and ticket construction are bounded. The reference implementation limits each ticket to **1 MiB** (an application limit, not a claimed universal Canon device limit). Exceeding it blocks with a split instruction before page composition. Split jobs keep only an intermediate physical plan during composition, then generate and validate a separate ticket for each complete-record/envelope PDF. File page indices restart at 1, JDF indices at 0; global sequence values retain their production identities.

Use `default_ticket.jdf` in the PRISMAsync ticket editor and inspect page programming before a proof print. Hotfolder tickets apply to the folder; filenames do not pair tickets with individual PDFs. Keep packages separate, and check any automated workflow's job-ticket override, banner/trailer and imposition settings. Stock availability is not queried. No printer/network submission, PostScript export, hardware-ready badge, or FreeFlow backend is included in this iteration.

Primary reference documentation:

- [Canon RunIndex page media examples](https://docs.cpp.canon/help?pageid=M113188.xml&tsm=ODP000004-v7.1EN.GB)
- [Canon Media Catalog selection](https://docs.cpp.canon/help?pageid=GUID-FAA94EE3-A7A0-4C8A-9E9B-E58CDD0D49F6.xml&tsm=ODP000133-4.7EN.US)
- [Canon hotfolder ticket selection](https://docs.cpp.canon/help?pageid=GUID-A517C218-84DE-4B8D-BE89-0DF6035E9129.xml&tsm=ODP000162-8.1.3EN.US)
- [Canon JDF version and submission constraints](https://docs.cpp.canon/help?pageid=M112343.xml&tsm=ODP000133-4.1.2EN.GB)

## Targeted validation

New tests cover 300 three-page letters (900 pages / 300 sheets per Stock), lazy 100,000-record planning, dynamic 1/2/5-page letters, stock conflicts and explicit blank insertion, template page identity, preview/output pixels, page sequences, barcode scopes and counts, cancellation/failure diagnostics, legacy versions, workflow production, and complete-envelope split packages with rebased tickets. A small ticket-limit test confirms limits apply per split file rather than the aggregate intermediate PDF.

UI checks cover batch assignment, profile save/load, bounded background preview, repairable invalid projects, workflow upgrade/Undo, application dark/light styles at 960×640 and a separate process using `QT_SCALE_FACTOR=2`. Offscreen snapshots were visually inspected with the application's bundled UI font; this does not replace hardware/printer testing.

Recorded checks: **157 related tests passed** across media, overlay, multipage, sequences and workflows; **18 UI/workflow checks passed in a separate 200% scale process** after the final navigation/upgraded-copy routing adjustments. Ruff passed on affected modules. Two existing format assertions were updated for template 10 / overlay 6, and generic data-step dialog parametrization now excludes Media Assignment because it has a dedicated dialog with its own tests; tests were not disabled to hide failures.

Repeatable synthetic benchmark:

```powershell
.venv-312\Scripts\python.exe -m scripts.benchmark_media --records 1000 10000 50000 --report docs/validation/media_benchmark_20261004.json
```

The recorded benchmark measures planning + CSV/SQLite/JDF only, not full PDF rendering or real printer throughput. Fixed-page planning stays lazy. The 50,000-record alternating-stock fixture exceeds the conservative ticket limit and correctly requests splitting. Full regression, Windows packaging and real Canon proof-print validation remain deferred to the agreed final batch acceptance.
