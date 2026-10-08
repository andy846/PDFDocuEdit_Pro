# v3.0.3 release validation

Windows x64 / Python 3.12. Evidence is retained under `build/release-3.0.3-validation/`. This document defines release gates; completion and exact package provenance are recorded in the GitHub release after the checks finish.

| Gate | Required evidence |
| --- | --- |
| Full Windows regression | `scripts/regression_suite.py --group all`; each module in a fresh process, JUnit/logs retained, crashes/timeouts count as failures. |
| Quality | Ruff, source verification, dependency consistency and whitespace checks. |
| Release CI | Exact version-tag commit: source quality, Windows automated/UI and Linux/macOS core suites. |
| Fresh packaging | `scripts/update_release.py build`; clean committed source, embedded commit/fingerprint/version and Composition enabled. |
| Frozen acceptance | `--composition-smoke`: CSV/TXT/Excel, CJK/fonts, sequences/rules, PDF/PS/overlay, two-source/two-template conditional routing, continuous I25 physical sheet numbering and final barcode decode. |
| New printing worker | Real frozen executable handles persistent `--print-worker` requests and multiple pages; PDF-printer output verified without touching a production printer. |
| Installation | Isolated QA AppId: install, frozen acceptance and uninstall without replacing production PDF associations. |
| Managed upgrade | Signed real-binary 3.0.2 → 3.0.3 upgrade in a fresh QA directory; scripted restart, preserved settings sentinel and retained previous version. |
| Integrity | Ed25519 signature/manifest, SHA-256 files, payload provenance and all uploaded asset sizes/server digests. |

Version contract tests change only their expected public version. The frozen I25 check now expects job-wide sheet values `00,01,02,03` instead of restarting per envelope, matching the user-confirmed production semantics; count/payload/decoding assertions remain.

Windows host QPrinter construction may emit a handled `0x80040155` diagnostic. A successful PDF-printer test is not evidence of native printer driver tray/finishing acceptance. Physical printer/inserter validation remains separate.

## Corrections found during release validation

- Windowed PyInstaller may clear Python standard streams. The print worker now explicitly binds its inherited Windows pipe handles when required; normal Python streams remain supported. A regression case exercises missing Python streams, ownership and cleanup, and the actual frozen worker is a separate gate.
- Restored the Template Designer's expected output-page heading through the existing physical-sheet planner, including duplex blank backs. Invalid print-media drafts display a review message.
- Overlay barcode size/payload prechecks now retain the affected object ID in errors, allowing Review object to select the actual failing item. The original live-preview test remains intact.
- The regression runner uses UTF-8 for diagnostics so a Big5 Windows console cannot abort the suite while printing Unicode failure evidence. Initial failed logs are retained; no assertion is skipped to obtain a successful run.
