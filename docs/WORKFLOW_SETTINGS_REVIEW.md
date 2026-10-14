# Designer and Visual Workflow settings / review

## Operator flow

1. Template Designer: layout, fields, direct barcode Content or Barcode Logic; Paper / Tray and Simplex/Duplex.
2. Workflow: choose template/data jobs, mappings, transforms, filtering/sorting and explicit overrides.
3. Check & Preview: inspect complete data snapshots; inspect logical and physical print plans. Step checks never publish or authorize.
4. Accept data & jobs: accept records/mappings/exclusions and selected jobs. This is not production authorization.
5. Production Review: check exact source, template, print media, barcode and destination bindings; resolve Issues, acknowledge actual warnings and Confirm production.
6. Generate, validate/reconcile, atomically publish and inspect outputs/reports.

## Settings precedence and compatibility

`workflow.media_settings` is the only settings-source resolver. New Media Assignment nodes carry `settings_source: project`; explicit overrides carry `settings_source: workflow`. The flag is stripped before the existing `MediaSpec`, Template/Overlay serializers and engines. Existing nodes with no flag remain overrides; legacy disabled-media Overlay nodes retain their prior duplex behaviour. New explicit disabled-media overrides can set Simplex/Duplex without constructing Stocks.

A saved workflow containing the new flag requires this reader. Previous readers reject that node rather than silently applying different printing settings. Existing `.pdflow`, `.pdcx`, Overlay and generic barcode profiles remain readable; no template format or public version is changed.

Template/Data/Media signatures, immutable prepared snapshots and signed ProductionAuthorization remain authoritative. No new PDF, print-planning or approval engine is introduced.

## Physical pages and barcode checks

`BatchJob.pages_per_record` retains its physical-output meaning because split generation uses it. `data_summary.print_plan.logical_pages_per_record` separately records template page count. Expected pages, sheets and blank backs come from `build_print_plan`, including duplex with Media disabled. Preview, inspection, review and final generation share the resolved media.

`expected_barcodes` accumulates checked payloads. Incomplete/blocked/cancelled checks show **Not fully checked**, not a verified zero. No barcode is required merely because a template exists; existing Inserter profile requirements remain.

## Freshness and navigation

Background source observations use size/mtime only to inform the UI. Hash validation still protects production and inspection reads. Saving/opening a changed template or returning to a workflow requires a new manual check; there is no automatic full rescan. Open dirty templates immediately invalidate unfinished related jobs. Changes to branch-wide input data invalidate the shared sequence across unfinished branches. Completed verified results remain available.

Media issues use the effective source and exact node ID. Inherited project issues return to Design and Paper / Tray; object issues select the original object/page. Workflow overrides return to the correct node. Return to Workflow does not save or recheck automatically. Production output-folder preference is independent of profile/image browsing.

## Targeted acceptance

- Legacy and explicit media source round-trip; inheritance/override inspection, review and actual generation agree.
- Three logical pages × two records in duplex produce eight output pages, four sheets and two blanks; split packages keep physical ranges.
- Cancelled/blocked barcode checks do not label partial counts complete.
- Source changes revoke data acceptance, invalidate checks and preserve prepared evidence and completed outputs.
- Branch input change invalidates shared-sequence approvals; stale jobs cannot be accepted again until Check & Preview.
- Review returns to correct branch/node or source template; output picker remembers only explicit production selection.
- Data acceptance does not sign a ProductionAuthorization. Existing direct-worker/engine negative approval tests remain mandatory.
- Related Qt checks include narrow 960×640 layouts, light/dark and scale 2. Full regression, native Windows/macOS packaging and actual printer/inserter proof remain separate release gates.
