# macOS parity — development

Baseline: Windows v3.0.3 + production review (`85b57d4`). Work is isolated on
`codex/macos-parity`; no Windows release or public version change is implied.

Apple Silicon is the initial target. OCR, Intel and managed automatic updates
are excluded from this first internal DMG. Native and printer acceptance must
run on macOS; Windows tests alone are not Mac acceptance evidence.

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

The build refreshes qpdf hashes after PyInstaller relocation/signing and seals
the application afterwards. Fonts must retain their original hashes. Frozen
workers restore only their inherited POSIX standard streams. The packaged zbar
loader resolves the owned library rather than searching a developer's Homebrew.

`.github/workflows/macos-parity.yml` builds on an arm64 macOS runner and retains
the DMG/checksum and test evidence as an internal artifact. No GitHub Release or
Windows deployment is published by this workflow. Copy/replace the application
after closing it; Qt user settings and external projects remain outside `.app`.

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
- OCR, Intel, managed automatic updates, new template/workflow schemas, and
  printer-specific tray guarantees are excluded from the first candidate.

## Validation record

Windows: initial 29 protection tests passed. An additional isolated six-module
run passed 64 tests (entrypoint, printing, update UI, fonts, workspace modes,
shortcut scopes), with no failures/errors/skips. Mac CI outcomes are recorded
separately; do not interpret these Windows results as Mac acceptance.
