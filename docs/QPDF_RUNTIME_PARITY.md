# qpdf runtime parity - issue #14

All PDF operations, Font Preflight and Composition use `core.pdf_runtime.qpdf_executable()`. Font repair still requires successful independent `qpdf --check` before publication; unavailable validation is never accepted. No public version or project format changes.

## Preparation

Run `python -m scripts.prepare_composition_assets`. Windows retains its pinned x64 binary/DLL bundle. macOS ARM64 and Linux build qpdf 12.4.2 from the existing `build_assets/macos/SOURCES.json` source pin (SHA256 `8a58af5b6141319287c1883bec8bd1bd545b7567b7fc5e6ce5d25a1c85f36397`). The source is verified before extraction. Native staging records hashes, platform and source pin and retains LICENSE.txt / NOTICE.md (Apache-2.0).

Native prerequisites: CMake, a C++20 compiler, zlib and libjpeg development libraries. Linux CI installs cmake/g++/zlib1g-dev/libjpeg-dev; Mac core CI installs cmake/jpeg-turbo. This is a build-time requirement. Installed applications use their bundled executable without downloading tools. Linux is a CI/runtime target, not a new application release.

`--fonts-only` explicitly prepares only fonts and is insufficient for Font Preflight repair. `--verify-only` performs strict validation without rebuilding. Explicit preparation can rebuild invalid native caches from the same pinned source. The runtime itself always rejects missing files, mismatching hashes/platform/architecture or missing execute permissions.

## Packaging and acceptance

The existing Mac native preparer shares the build/staging helper. PyInstaller includes the native binary and manifest-verified notices. Existing finalization refreshes hashes after relocation/signing. Frozen acceptance creates a deterministic PDF and runs the bundled executable with `--check` from an installed app under a path with spaces, with development library overrides removed and PATH restricted to system locations. Existing dynamic-library and ARM64 audits remain mandatory. Windows binary assets are unchanged.

## Evidence

Local Windows focused suite: 88 passed; Ruff passed; Windows assets `--verify-only` passed. Local source verification cannot pass until this checkout has the existing pinned Ghostscript runtime (`Ghostscript/bin/gswin64c.exe`). Actual remote Linux/Mac core, Windows automated/UI and native Mac installed-app results are pending. Synthetic fixtures do not prove physical printer behavior. No GitHub Release was produced.
