# Visual Workflow · Mail Merge Production

Implemented in the v3 development branch; this is not a public release or a full regression/packaging approval.

## Entry points

- Document Designer start page, main Workspace menu and command palette: **Visual Workflow…**.
- Choose **Mail Merge Production** for template/data pairs, or **PDF Processing** for the existing extraction/grouping/overlay pipeline.
- An existing saved template can use **Production → Create Workflow from Project…**. Invalid drafts or active template tasks must finish first.

## Working with a reusable recipe

The Mail Merge chain is Data Input → Field Mapping → Letter Template → Fields & Sequences → Preview & Review → Compose → Validate & Reports.

1. In Review, add an explicit template/data pair. CSV/TXT and Excel use the existing import-settings and mapping dialog. Generated-record templates may omit a data file.
2. Each row has its own template, worksheet/import settings, named mapping profile, sequence-start overrides and PDF filename. Defaults come from the template; no record matching is guessed from filenames.
3. Check & Preview creates owned snapshots of template backgrounds, images, exact font faces and imported SQLite records. It reports missing mapped fields, missing resources, sequence collisions, unknown sequence overrides and duplicate output filenames.
4. Select a checked row and preview the first, last or a specified record/template page. Only that page is rendered. Source changes require checking again before production.
5. Select the checked jobs to approve, then Run Ready Jobs. The confirmation lists the selected production count, records, expected pages and output root.
6. Each job has an independent sequence and PDF, control CSV, JSON job log and any glyph-repair report. Layout, font selection, conditional rules and barcode definitions remain in the template Designer.

## Shared UI changes

- Build / Review / Run navigation and contextual primary actions replace the crowded toolbar. File and step commands remain in menus.
- Searchable icon step library, collapsible side panels, compatible Add next step menu, compatible port feedback, grid snapping, explicit Auto Layout, zoom / Fit / Reset and keyboard node navigation.
- Node cards retain both summaries and text/symbol status. Wrapped connections pass between rows instead of diagonally through cards.
- Graph settings and progress update live items; canvas zoom, position and selection are retained. Deferred Qt item retirement remains in place.
- Batch and result tables use model/view, not one QWidget per row. A failed result can be opened for review; reports and validated output open from the selected result.
- Narrow layouts hide the step library by default and bound inspector width; panels remain available using Steps / Settings. Themes use the existing application palette and icons.

## Publishing and resume

Production runs sequentially in an isolated worker and reuses the existing bounded-page/chunk assembler. One critical record error stops that job, records its failure and allows the next approved job to run. Input hashes and checked-snapshot hashes are verified before each job. Successfully published files are never replaced by retries.

Output layout:

```
chosen-folder/
  batch-<batch-id>/
    batch.json
    batch-summary.csv
    <job-id>/
      <row-output-name>.pdf
      control.csv
      job.json
      ...optional glyph reports...
    <failed-job-id>-failed/
      control.csv
      job.json
```

Cancel waits for safe checkpoints, preserves completed results and leaves unstarted items pending/ready. Retry Failed rechecks unfinished items; approval is required before retrying. Run Remaining processes approved ready items only.

Workflow recipes use `.pdflow` version 2, project kind `mail_merge_workflow`. Existing version-1 `pdf_workflow` files keep their existing semantics. No template-format or public application-version change is required.

Saving a Mail Merge workflow also saves its job list in `<workflow-stem>.batch.json`. Explicit Save/Open batch list is available in Review → More. Recipes contain no imported customer rows. Batch records contain input references, settings, counts, results and history; temporary templates, SQLite snapshots and approval are not restored. Opening a record never starts production. Completed output hashes are checked when the queue is checked again.

Source data and templates still need to be available at their recorded locations. This change does not create a portable archive of all batch input files. Branches, hot folders, arbitrary scripts and field-value template routing are outside this milestone.

## Targeted verification

- 81 related tests passed together: new Mail Merge engine/UI, existing PDF workflow core/UI and existing production generation/reconciliation tests.
- Four subsequent malformed-record tests passed with the 18-case Mail Merge core suite; total unique relevant coverage is 85 cases.
- A separate 200% scale pass: 10 relevant canvas/narrow-layout/cancellation cases passed.
- Verified two-page × 100-record and three-page × 200-record jobs generate 200 and 600 pages; distinct mappings and independent sequence starts, Excel leading zeros, actual I25 failure continuing to the next job, fixed single-page previews, cancelled batches, source/snapshot changes, missing outputs, partial batches, legacy recipes and save/reopen.
- UI checks include rapid node selection, live item identity, invalid port connections, existing host shortcut routing, template-to-workflow handoff, dirty template guards, automatic single-page record preview, close cancellation, light/dark themes and 960×640 layout.
- Ruff and diff whitespace checks passed. One existing UI assertion was updated because the optional-step control intentionally moved from the top toolbar to the contextual canvas footer; its visibility test remains.

No full application regression, Windows package build or 50,000-record release benchmark was run in this milestone. Those remain part of the user's consolidated release validation.
