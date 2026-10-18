# Compact Designer Production console

## Scope

Presentation-only refresh of the Template Designer Production tab. The existing
PrintPlan, generation workers, output limits/naming, font substitution controls,
Production Review and authorization remain the sources of truth. No production
algorithm, public version, project format, dependency or release change.

## Layout and integration

- `composition/designer/production_console.py`: compact Production plan and
  Output settings cards, planned record/page/sheet metrics, read-only stock
  table, original settings controls, collapsible full job report and fixed
  review/result actions. Narrow layouts stack the cards. Missing or invalid
  planned totals are explicit rather than displayed as zero or stale values.
- `production_settings.py`: reuse the existing plan and extracted stock summary
  rows for both the original detailed summary and the compact presentation.
- `workspace.py`: attach the console to the existing Production stack position;
  forward generation lifecycle events without replacing existing result logic.
- `production_activity.py`: compact responsive progress header; preserve elapsed
  time, cancellation and indeterminate-stage behavior.
- `chrome.py`: place existing reports and error-recovery actions in the fixed
  footer. Existing callbacks remain connected.
- `styles/components.py`: scoped panel styling using existing theme tokens.
- `tests/composition/test_production_console_ui.py`: layout, state, safety and
  interaction regression cases. CI selection registered in `scripts/ci_plan.py`.
- `test_production_activity.py`: locate the console scroll area through its
  explicit attribute instead of the former layout index.

The full report remains available. A worker error expands it automatically and
sets the log status to Failed. The fixed error summary is one elided line with
full tooltip/report text, so long failures cannot push controls off screen.
Parent-owned deferred table sizing accommodates theme font changes safely.

## Verification — 2026-10-18

Windows/PyQt6 offscreen regression: **108 passed, 0 failed, 0 errors, 0 skipped**
across 12 modules: console, activity, compact layout, output limits UI, production
review UI, Designer page drafts/workspace, automatic font fallback, media UI,
Visual Workflow production review, CI selection and source contracts.

The 14 console tests also passed separately at **200% DPI**. Visual inspection
covered light/dark themes at 1280x720, 960x640 and 760x580 logical sizes, including
running and failed states. Keyboard focus reveals scrolled settings; result and
review actions stay outside the scroll area. No horizontal scrollbar appeared.
Independent review findings concerning long error messages and stale Running
labels were reproduced, fixed and rechecked. Pending timer destruction was also
checked. Targeted Ruff and Git whitespace checks passed.

Local evidence (not committed): `build/probes/production-console/`, including
`final-regression/result.json`, `final-high-dpi.xml`, `visual-result.json` and
rendered UI snapshots. Synthetic data only; no customer document processing.

macOS native appearance and owner interactive checks: **Not Tested** in this
change. No new performance worker or file scan was added. Resize only rearranges
widgets and sizes a bounded number of table rows; no production recalculation
is triggered by repaint/resize. Full application regression and real production
throughput were not rerun for this presentation-only change.
