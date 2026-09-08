# V2.5.4 Windows release build

Date: 2026-09-08. Delivery follows v2.5.3: Windows x64 Setup and Portable ZIP, each with a SHA-256 file. No macOS package is included. Artifacts are unsigned, matching the preceding release.

## Validation

- Canonical `scripts/build.py` on Python 3.12.14: completed successfully.
- Build preflight full pytest: 389 passed in 312.32 seconds; source verification and Ruff passed.
- PyInstaller clean build and Inno Setup compile: passed.
- EXE product version 2.5.4 / file version 2.5.4.0; Setup product/file version 2.5.4.
- Portable archive CRC: passed, 1,544 entries; archived EXE matches the built EXE.
- New controller/printing/atomic-IO modules are present in the embedded Python archive.
- Packaged Tesseract version smoke test passed. Packaged veraPDF/private JRE reports 1.30.2 through the production Java/JAR command.
- A generic build-helper BAT invocation failed when reused against the packaged path containing spaces. The product uses its direct Java/JAR command, which passed. This does not claim that the generic BAT helper supports every such path.
- Packaged EXE startup returned 0 via single-instance forwarding to the already-running application. The existing user window/documents were left open; this is not a fresh packaged-window or clean-machine installation test.
- Physical printers, clean-machine install/uninstall and macOS packaging were not tested in this release session.

## Artifacts

- `PDFDocuEdit-Pro-v2.5.4-Setup-Windows-x64.exe`: 201,693,198 bytes; SHA-256 `b750484a83f4d8833c9a6d3fe6b5d1725816f6336a729a53e4f46b16e5e1b8ce`.
- `PDFDocuEdit-Pro-v2.5.4-Portable-Windows-x64.zip`: 307,756,210 bytes; SHA-256 `2a32011068b840d096aa3fca8c8fe0b6769e60fb862a97aa1df8474f1b509e03`.

Release notes: [V2.5.4](RELEASE_NOTES_2.5.4.md). GitHub delivery uses tag `v2.5.4` and four uploaded assets.
