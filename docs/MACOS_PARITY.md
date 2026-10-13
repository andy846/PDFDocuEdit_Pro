# macOS parity — development

Baseline: Windows v3.0.3 + production review (`85b57d4`). Work is isolated on
`codex/macos-parity`; no Windows release or public version change is implied.

Apple Silicon is the initial target. The original manual-update candidate below
excluded account login and managed updates. The next phase adds both with the
same Windows core: see [account/update parity](MACOS_AUTH_UPDATES.md). OCR and
Intel remain excluded. Native and printer acceptance must run on macOS;
Windows tests alone are not Mac acceptance evidence.

## Build and deployment

On an Apple Silicon Mac with Python 3.12, use the pinned Python requirements:

```sh
python -m pip install -r requirements-macos.txt -r requirements-dev.txt
brew install cmake autoconf automake libtool gettext pkgconf
python -m scripts.prepare_macos
python -m scripts.prepare_verapdf
python -m scripts.build --composition
python -m scripts.macos_install_smoke --app 'dist/PDFDocuEdit Pro.app' --output build/macos-acceptance
```

Homebrew supplies **builder tools**, not end-user requirements. Source archives
are SHA-256 pinned in `build_assets/macos/SOURCES.json`. qpdf uses static libraries
and its native crypto provider; zbar uses the macOS iconv library. Windows
continues using its existing EXE/DLL manifest and updater protocol.

The bundle uses native arm64 helpers, installed outline fonts from the existing
Mac font directory service, the existing print/render/generation engines, and
Qt's platform shortcut mapping. Finder opens `.pdcx` and `.pdflow` through the
existing project host; PDF/PS/EPS continue through the background PDF queue.

Native Qt shortcuts already map logical Ctrl to Command on macOS. They are not
converted to Meta, which would incorrectly map back to physical Control.
Designer uses Command+Shift+Z as its primary redo binding and also accepts
Command+Y. PDF Workspace accepts both. User overrides and conflicts remain
authoritative. The Finder instance endpoint is short and user-scoped; existing
project files are identified by filesystem identity on Mac, respecting the
volume's actual case sensitivity.

The build refreshes qpdf hashes after PyInstaller relocation/signing and seals
the application afterwards. Fonts must retain their original hashes. Frozen
workers restore only their inherited POSIX standard streams. The packaged zbar
loader resolves the owned library rather than searching a developer's Homebrew.

`.github/workflows/macos-parity.yml` builds on an arm64 macOS runner and retains
the DMG/checksum and test evidence as an internal artifact. No GitHub Release or
Windows deployment is published by this workflow. The standalone DMG requires
manual replacement; the new **Managed** DMG runs the shared signed updater.
User settings and external projects remain outside `.app`.

## Gates and known limits

- Local Windows protection: update/build/file-routing contracts, installed font
  export, printing, mode switching and shortcut routing. The original Windows
  checkout must remain clean. Full Windows regression/build/installation gates
  remain required **before merge**.
- Mac source: use `python -m scripts.macos_test_plan` for isolated relevant modules.
- Mac installed app: run from a copied application in a directory with spaces,
  with development Python, DYLD, Ghostscript and Homebrew paths removed. Reject
  retained build-machine dylib references. Exercise real frozen font, review,
  generation and persistent-print workers; verify I25 decoding and PS output.
- macOS 13 is the deployment target, not a tested minimum-version claim. The
  hosted macOS 14 result cannot establish compatibility with macOS 13.
- Retina/trackpad, native menu behavior, Gatekeeper and real printer/DFE stock
  selection require operator testing on a real Mac.
- Cross-platform projects need their referenced source data/background assets.
  Saved portable font assets retain their existing format and restrictions;
  missing fonts must not be silently changed.
- The internal DMG is ad-hoc signed. Public distribution needs Developer ID,
  hardened runtime, timestamped signing, notarization and Gatekeeper acceptance.
- OCR, Intel, new template/workflow schemas, and printer-specific tray guarantees
  are excluded. Managed update/account acceptance is tracked in the new phase.

## Validation record

Windows: initial 29 protection tests passed. An additional isolated six-module
run passed 64 tests (entrypoint, printing, update UI, fonts, workspace modes,
shortcut scopes), with no failures/errors/skips. Mac CI outcomes are recorded
separately; do not interpret these Windows results as Mac acceptance.

After native IPC/project/redo fixes, five isolated Windows modules passed 88
tests, including all existing mode-switch and veraPDF fixture assertions.
The initial cloud Windows affected-test run reached its 20-minute time limit
without completing; this is **not** a pass or a substitute for the full merge gate.
The focused CI runner now reuses the existing per-module isolation and retains
all selected tests/JUnit evidence: mixed Qt application/style globals caused a
native crash when several UI modules shared one process. Crashes remain failures.

Native macOS source gate at `345d9b3` (Actions run `37880248212`): 21 modules,
345 passed, 1 Windows-registry-only font test skipped, zero failures/errors.
The actual Mac installed-font catalogue is checked separately in the frozen app.
The first packaging attempt rejected the moving latest veraPDF archive; its
fixed official 1.30.2 archive was verified against the original checksum without
changing the validator or Java version.

Native bundle gate at `f460932` (Actions run `37882683234`): the DMG build and
copied-app acceptance passed on macOS 14 arm64. The copied application ran with
Homebrew/development runtime paths removed. Checks covered installed fonts,
Chinese CSV import and record preview, Production Review, duplex I25 generation
(2 records, 8 output pages, 4 decoded barcodes), PDF reopening/searchable Chinese
text, PostScript output, the persistent print worker and offline veraPDF.
The validator check establishes that veraPDF runs; it does not assert PDF/A
conformance of the sample production PDF.

The final source gate at the same commit passed 345 tests across all 21 selected
modules, with one Windows-registry-only font test skipped and zero failures or
errors. The downloaded DMG was verified against its companion SHA-256:
`778d08a35aefac811567296a087eae1037fe265dda9a6f09b8b907571e10f1b5`.

Windows CI at the same commit (Actions run `37882683255`) passed. This is CI
protection evidence, not the full Windows release/build/install merge gate.

## Internal candidate delivery

Download the `macOS-arm64-internal-candidate` artifact from the successful
[Mac candidate run](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/37882683234/artifacts/11595915278).
The ZIP contains the DMG and its SHA-256 file under `release/`, test evidence
under `build/macos-tests/`, and copied-app results/screenshots under
`build/macos-acceptance/results/`. Artifact access requires repository access
and expires after 14 days; it is not a public release.

In Terminal, compare the downloaded DMG checksum with its companion file:

```sh
shasum -a 256 /path/to/PDFDocuEdit-Pro-3.0.3-macOS-arm64.dmg
```

Use the actual filename supplied in `release/`. The internal application is
ad-hoc signed and has not been notarized; macOS may require explicit operator
approval to open it. Record that result in the acceptance checklist below.

## Operator acceptance on the M-series Mac

The internal candidate is for local acceptance, not public deployment:

1. Close any existing Mac edition. Verify the downloaded DMG against its
   accompanying SHA-256 file and copy the app to Applications.
2. Open PDF, `.pdcx` and `.pdflow` files from Finder; a second launch should focus
   the running app without losing unsaved tabs. Reopen an already open project.
3. Check Command+S/O/Z/Shift+Z, text-field editing, mode switching, trackpad zoom,
   Retina sharpness, narrow windows and both themes.
4. Copy source data/background assets with a representative Windows project.
   Locate missing sources and fonts explicitly. Compare preview and PDF output
   against the Windows job: record/page counts, sequences, I25 values, reports
   and Production Review approval must agree.
5. Generate PDF + PS/JDF using neutral saved media profiles. Compare paper rules
   and duplex plans first, then run a small printer/DFE job and confirm the actual
   selected stocks. A generated PS file is not proof of hardware tray support.
6. Check the native print dialog, cancellation and reopening/saving projects.

Record Mac model, macOS version, printer/DFE, failures and the candidate commit.
The internal ad-hoc signature is not Developer ID/notarization acceptance;
public deployment remains a separate gate.
