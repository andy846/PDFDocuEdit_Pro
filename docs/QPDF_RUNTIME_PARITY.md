# qpdf runtime parity - issue #14

All PDF operations, Font Preflight and Composition use `core.pdf_runtime.qpdf_executable()`. Font repair still requires successful independent `qpdf --check` before publication; unavailable validation is never accepted. No public version or project format changes.

## Preparation

Run `python -m scripts.prepare_composition_assets`. Windows retains its pinned x64 binary/DLL bundle. macOS ARM64 and Linux build qpdf 12.4.2 from the existing `build_assets/macos/SOURCES.json` source pin (SHA256 `8a58af5b6141319287c1883bec8bd1bd545b7567b7fc5e6ce5d25a1c85f36397`). The source is verified before extraction. Native staging records hashes, platform and source pin and retains LICENSE.txt / NOTICE.md (Apache-2.0).

Native prerequisites: CMake, a C++20 compiler, zlib and libjpeg development libraries. Linux CI installs cmake/g++/zlib1g-dev/libjpeg-dev; Mac core CI installs cmake/jpeg-turbo. This is a build-time requirement. Installed applications use their bundled executable without downloading tools. Linux is a CI/runtime target, not a new application release.

`--fonts-only` explicitly prepares only fonts and is insufficient for Font Preflight repair. `--verify-only` performs strict validation without rebuilding. Explicit preparation can rebuild invalid native caches from the same pinned source. The runtime itself always rejects missing files, mismatching hashes/platform/architecture or missing execute permissions.

## Packaging and acceptance

The existing Mac native preparer shares the build/staging helper. PyInstaller includes the native binary and manifest-verified notices. Existing finalization refreshes hashes after relocation/signing. Frozen acceptance creates a deterministic PDF and runs the bundled executable with `--check` from an installed app under a path with spaces, with development library overrides removed and PATH restricted to system locations. Existing dynamic-library and ARM64 audits remain mandatory. Windows binary assets are unchanged.

## Evidence

Local Windows focused suite: 88 passed; Ruff passed; Windows assets `--verify-only` passed. Local source verification cannot pass until this checkout has the existing pinned Ghostscript runtime (`Ghostscript/bin/gswin64c.exe`). Remote validation on product source `a5681ae601b0b5f3a3a9d8ae20879920a8028162`:

| Gate | Result / evidence |
| --- | --- |
| Linux core | 340 passed, 14 existing platform skips |
| macOS ARM64 core | 340 passed, 14 existing platform skips |
| Windows UI | 970 passed, zero skips/failures |
| Mac native application / Managed / private admission | Passed; [native run](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/38393146954) |
| Mac platform acceptance tests | 224 passed, 1 platform skip, 14 modules |
| Windows automated | Passed on failed-job-only rerun: 1,461 passed, 3 platform skips, 114 modules; performance smoke passed. Initial same-source attempt had one inactive-page navigation failure; the exact case also passed locally. |

[Full CI](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/38393152221) includes the full existing core/UI suites. No test has been disabled or skipped to pass this repair.

The native artifact report confirms qpdf 12.4.2, `qpdf_independent_check.status=OK`, exit code 0, and an executable inside `Installation with spaces/PDFDocuEdit Pro.app/Contents/Frameworks/build_assets/composition/qpdf/qpdf`. Font repair's three original failures pass on both native core platforms.

Native testing exposed two outdated test assumptions that were corrected: the frozen QA generator now supplies the genuine session-bound review receipt over private stdin, including for synthetic PostScript fixtures; the mode-transition test waits for completion within its existing deadline instead of a fixed 250ms. The production authorization service and animation behavior are unchanged. Local signed-QA/authorization/runtime tests: 38 passed; the exact animation case passed.

Earlier runs retain their actual failures: [old native harness](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/38390609145), [fixed-delay animation assertion](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/38391892467), and existing Windows UI crashes/errors in `test_p5_ui` / `test_large_organizer`. The later native run and Windows UI gate passed. The exact `test_p5_ui` module passed locally (4 cases). These records are not replaced or described as successful. Synthetic fixtures do not prove physical printer behavior. No GitHub Release was produced.

Final full CI conclusion: success (attempt 2), retaining successful source quality, Windows UI and Linux/Mac core jobs. The tested product source is `a5681ae`; the following documentation-only commit adds evidence and the Symantec support note without rerunning unchanged product gates. No main/default branch merge, version bump, release or antivirus submission was performed.
