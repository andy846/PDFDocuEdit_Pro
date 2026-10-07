# v3.0.2 release validation

Windows x64 / Python 3.12. This document defines the release gates and evidence
locations. Completion results, release commit and artifact hashes are recorded
in the GitHub release after these gates pass; this document alone does not
assert successful publication.

| Gate | Procedure / evidence |
| --- | --- |
| Full Windows regression | `scripts/regression_suite.py --group all --output build/release-3.0.2-validation/regression`; every module in a fresh process, with JUnit/logs and crash failures retained. |
| Quality | `python -m ruff check .`, `python scripts/verify_source.py`. |
| Full CI | Version-tag CI on the exact release commit: Windows core/UI, Linux/macOS core, quality and performance smoke. Live Actions status is authoritative. |
| Fresh packaging | `scripts/update_release.py build`; embedded `update_build.json` records exact clean source commit, fingerprint, version and enabled Designer. |
| Frozen acceptance | The production executable's `--composition-smoke` at 200% scale: dark/light narrow layouts, CSV/TXT/Excel, CJK/fonts/repair, sequences/rules, PDF/PS, overlay and reconciliation. |
| New features in frozen worker | Two data files × two templates: eight routed records / twelve pages, batch sequence, check before explicit approval; zero-start Inserter I25 on two odd three-page duplex records: eight output pages / four decoded marks. Exact cross-page repeat coordinates are checked. |
| Installation | `scripts/composition_install_smoke.py`: isolated QA AppId, no production PDF-handler/shortcut changes; install, frozen acceptance, uninstall. |
| Upgrade | `scripts/release_update_smoke.py --baseline-version 3.0.1`: real baseline/new binaries, signed update, scripted launcher restart, preserved isolated settings sentinel; current=3.0.2, previous=3.0.1, stable. This is not a manual updater-UI test. |
| Integrity | Verify all three SHA-256 files, Ed25519 manifest/signature, ZIP metadata/source commit and uploaded asset sizes/hashes before making the draft Latest. No private key is packaged. |

Evidence is retained under `build/release-3.0.2-validation/`. Test contracts
change only the expected public version from 3.0.1 to 3.0.2; no regression
assertions are removed or disabled. Two media review fixtures now explicitly
assign their initial Stocks: the newer duplex UI intentionally leaves new
template assignments blank instead of guessing the first three Stocks. Their
page identity, deleted-rule restoration and per-mode draft assertions remain.

Printer stock selection and inserter barcode read acceptance require physical
device tests and are not established by software validation.
