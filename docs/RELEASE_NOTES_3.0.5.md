# PDFDocuEdit Pro v3.0.5

## PDF Workspace navigation

- Six compact tool categories with preserved existing actions and commands.
- Editable, persistent Favourites (up to eight tools), compact category menus,
  searchable descriptions/legacy aliases/custom shortcuts and keyboard navigation.
- Responsive sidebar restores the user's expanded preference after temporary
  layout constraints. Dark/light themes and high-DPI controls remain consistent.

## PDF Production Tools

- Fonts, Flatten and Repair / Normalise share a persistent PDF Workspace tab,
  source snapshot, background progress and results. One processing operation
  runs at a time; originals are retained and outputs are validated atomically.
- Overview combines read-only structure, annotation/form and font checks.
- Editor sources include unsaved changes; changed sources invalidate old checks.
- Results include per-file status, remaining issues and JSON/CSV audit export.
- Safe Embed Fonts requires authorized, verified original fonts and a trusted
  reference. Native repair is limited to supported TrueType / WinAnsi cases;
  CJK/CID fonts are inspected, never silently replaced.
- Rasterisation, signature-invalidating changes and destructive normalisation
  require explicit choices. This tool cannot repair every damaged PDF.

## Startup and account experience

- Valid saved approval moves directly from Splash to the main window.
- When sign-in is required, Splash closes before the sign-in window appears.
- Successful sign-in opens the workspace without a second Splash.
- Windows/macOS share the startup handoff; Managed readiness follows a painted
  sign-in or workspace rather than waiting for account input.

## Downloads and updating

Windows x64: account-enabled Managed installer and portable package.
macOS 13+ Apple Silicon: account-enabled Managed DMG testing build, ad-hoc signed
and **not Apple notarized**. Initial launch may require system approval.
Intel, Mac OCR and production printer/DFE parity are outside this release.

Use Help / Check for Updates, download, save work, then Update and Restart.
All three signed update routes remain available, including the original v3.0.3
Windows Managed launcher route. Templates/workflows/barcode formats and the
update trust key are unchanged. Account approval supports offline reopening.

Publication is subject to native and candidate operator gates in UNIFIED_RELEASE.md.
