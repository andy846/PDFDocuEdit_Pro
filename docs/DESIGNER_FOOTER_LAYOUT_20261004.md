# Designer footer layout correction — 2026-10-04

## Reproduction and correction

A rendered instance of the integrated template Designer showed a status bar
height of **1 logical pixel**. Its status labels had zero height at the bottom
of the main window. Qt's styled status-bar layout collapsed the footer under
the existing `min-height: 0` rules.

Both template Designer and PDF Overlay now use `DesignerStatusBar`. It reserves
the font height plus padding and the height needed by visible status controls.
Font, style, show, and layout changes update the explicit minimum height; a
size-hint override alone was insufficient for QMainWindow's native layout.
Long template messages retain their existing elision and full-details access.
Overlay's embedded size grip is disabled, matching the template footer.

In the rendered Noto Sans 9pt sample at 960×640, the corrected footer occupies
23 logical pixels and the message fits entirely within it. The root and
inspector stay within their existing boundaries. This was verified with a
separate rendered test instance; the Windows screen-reading helper failed to
start, so the user's live window was not captured or modified.

## Targeted checks

- Eight integrated footer cases passed with the offscreen backend: template and
  overlay, light/dark themes, 760×580 and 960×640, with repeated mode switching.
- The same eight cases passed on the native Windows Qt backend with
  `QT_SCALE_FACTOR=2`.
- Five existing compact-layout/message cases passed, including long messages,
  keyboard details access, record navigation, and active progress/cancel controls.
- The compact-layout canvas budget now excludes the separately reserved readable
  footer. The existing 170-pixel budget for other chrome is retained, and a new
  assertion requires a readable footer. The prior total budget relied on the
  one-pixel collapsed status row.
- Ruff and whitespace checks passed. No full regression or packaging was run.

The running user instance remains open to preserve current work. Saving and
restarting is required to load this code change.
