# Popup smooth-edge follow-up

Date: 2026-10-30. D-drive local `main`; baseline commit
`0ec0765377cf1dfbc3dc5c1b4fa70378bf2728fe`. Windows / Qt 6.8.2 / `.venv-dev`.
No version bump, branch, commit, push, package or release. Existing Extract/export
progress changes and `BOCHK.pdmp` were preserved.

## Root cause and correction

The earlier QRegion solution removed square corners but retained a binary,
integer-coordinate cutout. It cannot represent a partially covered edge pixel;
this was particularly visible against a white PDF. Initial tests checked shape,
clipping and interaction, not smooth coverage. Qt explicitly documents this
limitation of [widget masks](https://doc.qt.io/qt-6/qwidget.html#setMask).

The common implementation now retains an opaque theme-colored body and uses a
per-pixel alpha fringe for the 14-logical-pixel QSS rounded border. It does not
reduce whole-window opacity or introduce blur. Popup/ToolTip window types remain
unchanged. Existing theme colors, padding and keyboard behavior are retained.

- `styles/popups.py`: hidden menus prepare through aboutToShow; hidden combo
  containers prepare when their owning control is shown. Only widget filters
  are installed, preserving the earlier global-filter teardown fix. No window
  flags are changed during polish or while a popup is open. A coarse fallback
  remains for a popup first encountered while already open.
- `styles/theme.py`: the standard QTipLabel opacity style hint supplies its
  pre-display setup point; the polish-depth guard prevents preparation during
  polish. Alpha must be set before the frameless hint can initialize/recreate
  a native surface; reversing the order failed the first native menu display.
- Private Qt popup wrappers can be temporary. Readiness, registration and mask
  fallback metadata now live on the QObject as dynamic properties rather than
  ephemeral Python wrapper attributes. No popup references are retained.
- A translucent private QFrame does not automatically fill its background.
  The combo parent Paint event explicitly draws the existing QSS PE_Widget
  surface once; Qt continues painting/handling its child item views normally.
  This preserves an opaque body for editable and noneditable dropdowns.
- `tests/test_popup_shapes_ui.py`: pixel coverage (transparent corner, opaque
  body, partial-alpha fringe), no hard mask on prepared surfaces, first display
  with an existing native handle, wrapper reuse, theme changes, menus/submenus,
  selection, Esc, repaint behavior, cleanup and magnifier exclusion.

## Verification evidence

All artifacts below are local under `build/probes/popup-corner-audit/`.
Original failed logs are retained; no failed result was changed to passed.

| Final check | Result |
| --- | --- |
| Seven existing regression modules | 122 passed, 0 failed/skipped; per-module exit 0 in `verified-alpha-final/result.json` |
| Final popup module, offscreen | 11 passed; `final-offscreen-popup.xml` |
| Popup module at 150% / 200% offscreen | 11 + 11 passed; `final-popup-dpi150.xml`, `final-popup-dpi200.xml` |
| Popup module on native Windows, default effects retained | 11 passed; `final-native-popup.xml` |
| Native surface/pixel matrix | 36/36 passed: six surfaces x two themes x actual DPR 1.0/1.5/2.0 |
| Ruff, verify_source.py, git diff --check | Passed |

The main regression total is 133 (122 existing + 11 final popup cases). The
extra DPI checks, native pytest run and 36 native matrix cases are separate
executions, not additional unique test definitions. The seven existing modules
are UI regressions, shortcut customization, document windows, P2/magnifier,
tools port, CI plan and source contracts. A full release suite was not run.

The first forced-native-handle test initially asserted the actual surface format
on offscreen too. Control probes showed that plugin always reports -1, even for
correct alpha output; Windows reports 8. The test now checks requested alpha and
rendered pixels everywhere, plus actual native format on Windows. No unnecessary
native-window destruction was added to production.

Native editable dropdowns can initially show a temporary Windows roll-effect
window. The interaction test waits for the actual dropdown to be exposed, then
retains all opaque-body and fringe assertions. The default-effects native run
passes. The separate steady-state matrix disables effects only in its synthetic
QA process to measure final pixels deterministically; it changes no OS settings
or product preferences.

The native matrix uses the Windows Qt backend and verifies an actual layered
HWND, empty binary mask, corner alpha 0, body alpha 255 and partially transparent
edge pixels. Actual widget DPR values are in `native-smooth-steady-1.0.json`,
`native-smooth-steady-1.5.json`, `native-smooth-steady-2.0.json`. The host screen
used DPR 2; synthetic QA scale factors 0.5/0.75/1 produced the actual 1/1.5/2
surface ratios. No physical monitor settings were changed.

Reproduce the popup checks with `.venv-dev/Scripts/python.exe -m pytest
 tests/test_popup_shapes_ui.py -q`, selecting `QT_QPA_PLATFORM=offscreen` or
`windows` before launch. Existing regressions run separately using
`scripts/regression_suite.run`. The local native QA harness is
`build/probes/popup-corner-audit/native_smooth.py --check`.

## Render artifacts and remaining acceptance

`smooth-dark-menu-1.0.png` and other `smooth-<theme>-<surface>-<DPR>.png` files
are Qt component renders from the native Windows backend, not desktop-compositor
screenshots. A fresh Computer Use screenshot could not be obtained: its Node
kernel still failed sandbox setup. Read-only/QA commands resumed through the
approved ordinary local executor. Do not treat component renders or HWND checks
as completion of every physical-monitor visual scenario.

Not Tested: macOS/Linux native rendering, physical mixed-DPI monitor movement,
all screen-edge/background combinations, full packaged-app UAT, and measured
whole-application startup performance. Preparing a visible combo initializes
its hidden item view earlier than lazy first use; no repeated scans, workers or
continuous timers were introduced, but startup cost was not benchmarked.

Owner UAT: after saving work, reopen the D-drive development app when convenient.
Check the reported corner against a white PDF, short/multiline hover text,
editable/noneditable dropdowns, submenus, arrows/Enter/Esc, clicking outside and
light/dark changes. The running product was not automatically closed/restarted.


## Release-gate lifetime follow-up (2026-10-30)

The later full release gates exposed application teardown faults that the initial
popup-only visual checks did not catch. A shared application-owned event filter
could be retired while hidden widget trees still existed. Each known surface now
owns its own filter; one application-owned coordinator still handles registration.
The initial widget-owned revision used a tuple property for wrapper retention;
the final registry correction below supersedes that mechanism. No popup
references are retained by the coordinator, and registration remains idempotent without global filtering,
new timers or worker threads.

The three ownership tests failed before the fix. The final popup module has 14
cases; four formerly failing UI modules passed five fresh CPython 3.12.10 processes
each. Development results do not replace the fresh full native release gate.
Detailed failed attempts and source/run identities are recorded in
[the v3.1.3 release validation](RELEASE_VALIDATION_3.1.3.md).

Final lifetime revision development checks: 137 related regression cases; 42 native
Windows popup cases across three DPI settings; 36 native layered-surface/pixel
cases, all passed. These native images are component renders, not desktop
compositor screenshots. Ruff, source verification and whitespace checks passed.


### Final filter-wrapper retention correction

The fourth release gate showed that the intermediate tuple-property approach
still failed interpreter shutdown. The coordinator now retains only Python event
filter wrappers in a dictionary, pruned by each filter's Qt destroyed signal.
Each filter remains parented to its watched widget. No native PyObject-valued
property retains the callback owner; no watched-widget references are kept.
Collection tests verify both discarded menus and destroyed filter wrappers are
released. A subprocess printing/preferences regression failed before this change
with 8 passing assertions followed by a native fault; it passes after the fix.

Final related checks: 139 passed; four affected modules each passed five fresh
CPython 3.12.10 processes. Native pytest: 48 passed across three DPI settings.
36 native pixel assertions passed, but one custom matrix process failed at exit;
10 exact repeats passed without reproducing it. That failed probe remains a known
validation limitation with its raw log retained. Full frozen-candidate CI and
packaged upgrade gates are recorded independently in the release validation.
