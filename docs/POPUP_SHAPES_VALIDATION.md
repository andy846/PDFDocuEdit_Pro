# Solid rounded popup validation

> Follow-up: this records the initial hard-mask implementation. The owner
> subsequently found visibly jagged edges; the current alpha-edge implementation
> and final evidence are in [the smooth-edge report](POPUP_SMOOTH_EDGES_VALIDATION.md).

Date: 2026-10-30. Baseline: D-drive local `main`,
`0ec0765377cf1dfbc3dc5c1b4fa70378bf2728fe`. Windows, `.venv-dev`.
No application version, dependency, project format, branch or release changed.
The pre-existing Extract/export progress fix and user files remain untouched.

## Implementation and maintenance

- `styles/popups.py`: one application-owned coordinator. The existing proxy's
  `polish()` only registers a filter on known popup widgets; it does not change
  flags, masks, native handles or styles during polish. Actual shaping waits
  for Show. Resize, palette/style/DPI changes and Paint restore the outer
  `QRegion` mask as needed. Size/radius/DPI caching and mask comparison avoid
  redundant `setMask()` calls. There are no timers, workers or retained popup
  references.
- `styles/theme.py`: retains the existing proxy ownership and spin-box glyph
  painting; removes translucent/no-system-background popup attributes.
- `styles/components.py`: solid theme surfaces, `R.LG` (14 logical pixels),
  Tooltip padding 8 vertical / 12 horizontal. The combo's private outer frame
  owns its border and rounded background; its inner list is transparent.
  Qt's private combo frame requires a local stylesheet to apply this border;
  that small stylesheet is refreshed only when its theme text changes.
- Standard text Tooltips are identified by `QTipLabel` plus `qtooltip_label`.
  Magnifier labels, native file dialogs, document previews and normal dialogs
  are excluded. These Qt-internal identifiers must be rechecked on Qt upgrades.
- `tests/test_popup_shapes_ui.py` is in the existing `scripts/ci_plan.py`
  UI list. The former translucent-menu assertion in `test_tools_port.py`
  now checks the approved solid surface, actual clipping and opaque content.

## Investigated failures

The initial tests reproduced missing masks on menus, combo containers and
standard Tooltips. A later pixel check caught the combo's missing outer border;
repolishing application QSS alone did not fix Qt's private container.

An initial QApplication-wide Python event filter also caused a native access
violation after the seven P2 UI assertions had passed. It reproduced with an
empty filter, with parentless ownership, and with matched import order. Baseline
and filter-disabled controls exited normally. Replacing global filtering with
widget-only registration passed both fresh-process and combined P2/popup tests.
The underlying Qt/SIP destructor defect is not established; the isolated trigger
is avoided. No fixture cleanup workaround or relaxed P2 assertions was used.
Earlier failed logs remain in the local probe folder.

## Automated verification

Fresh-process execution uses `scripts/regression_suite.run`, preserving native
crashes/nonzero exits as failures. Final logs/JUnit/results are local under
`build/probes/popup-corner-audit/verified/`.

| Module | Passed | Failed / skipped |
| --- | ---: | ---: |
| test_popup_shapes_ui.py | 8 | 0 / 0 |
| test_ui_regressions.py | 8 | 0 / 0 |
| test_shortcut_customization.py | 3 | 0 / 0 |
| test_document_windows.py | 28 | 0 / 0 |
| test_p2_ui.py (including magnifier) | 7 | 0 / 0 |
| test_tools_port.py | 55 | 0 / 0 |
| test_ci_plan.py | 12 | 0 / 0 |
| test_source_contract.py (separate final check) | 9 | 0 / 0 |

Total: 130 passed, zero failures/skips; every module exited 0. The eight popup
tests were additionally repeated with `QT_SCALE_FACTOR=1.5` and `2`: another
16 passed, zero failures/skips. This is offscreen coverage, not native visual
acceptance. Tests cover hidden polish, menu/submenu geometry, Enter selection,
editable/noneditable long combos, light/dark borders, Tooltip reuse/magnifier
exclusion, theme reuse, mask-cache behavior, reset repair, dynamic destruction,
two owners and Esc dismissal. Keyboard regression and viewer/window cleanup
remain in the existing suites.

Ruff, `scripts/verify_source.py` and `git diff --check` passed. Independent
read-only review found no remaining concrete blockers in this scope.

Reproduce each listed module with `.venv-dev/Scripts/python.exe -m pytest
tests/<module> -q` in a separate process. For DPI repeats set
`QT_QPA_PLATFORM=offscreen` and the desired `QT_SCALE_FACTOR` before launch.
Also run Ruff on the changed Python files, `scripts/verify_source.py`,
`tests/test_source_contract.py` and `git diff --check`.

## Native Windows observations

Only synthetic QA windows were used; no customer PDFs or application settings
were loaded. Native Windows screenshots were captured with Computer Use.

| Configuration | Actually observed |
| --- | --- |
| Dark, 100% | Menu and multiline Tooltip: rounded actual outer corners |
| Light, 150% | Long combo: border, rounded container, scrolling and selection |
| Dark, 200%, final widget-only implementation | Menu and multiline Tooltip: clipped corners, readable full text; keyboard opening and Esc; QA process exited 0 |

The 100%/150% captures preceded the final event-filter lifecycle change; 200%
was repeated with the final implementation. Mouse targeting the 200% QA window
initially reported missing monitor geometry; keyboard observation/action was
used successfully. No OS DPI settings were changed.

Local screenshot evidence:

- Before, 100%: `build/probes/popup-corner-audit/before-native-tooltip-2.png`.
- After, 100%: `build/probes/popup-corner-audit/after-native-tooltip-2.png`.
- Final after, 200%: `build/probes/popup-corner-audit/after-final-tooltip200-2.png`
  and `after-final-menu200-2.png` in the same folder.
- Light combo, 150%: `build/probes/popup-corner-audit/after-native-combo150-2.png`.

These local-only artifacts are not committed. The currently running product
was not restarted or closed. Only owned synthetic QA windows were closed.

## Remaining manual acceptance

Not Tested: macOS/Linux native display; physical mixed-DPI multi-monitor moves;
the complete theme/DPI matrix; all background colors and screen-edge placements;
native multi-level hover/focus return and every product-specific menu entry.
No new packaged build or full release regression was requested or run.

Owner UAT: restart the development app when convenient; check PDF Workspace
right-click and toolbar menus/submenus, Designer menus, editable/noneditable
dropdowns and short/multiline hover text. Exercise arrows/Enter/Esc, clicking
outside, focus return, long-list scrolling, light/dark switching and moving
between actual monitors. Confirm the magnifier keeps its original shape.
