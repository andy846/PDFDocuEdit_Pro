# v3.0.1 release validation

2026-10-06, Windows x64 / Python 3.12. Packaged acceptance and integrity checks
completed locally. Publication requires all applicable [PR #8 checks](https://github.com/andy846/PDFDocuEdit_Pro/pull/8/checks)
and version-tag CI to pass; their live status is authoritative for the CI gate.

## Completed development checks

- 79 targeted Workflow tests passed; 9 CI-scope tests passed; Ruff passed.
- 960×640 at 200% scale: light/dark node settings and paginated results inspected.
- In-app README construction test passed after the documentation update.

## Windows package acceptance

| Check | Actual result |
| --- | --- |
| Build | Fresh PyInstaller app, managed Launcher, signed Update ZIP, Managed Portable and Inno Setup completed. |
| Frozen UI/production | 200% scale, light/dark and narrow Designer layout; 100 records / 200 pages, Excel/XLS, CJK, sequences, conditions, glyph repair, barcode decode, overlay and 6-page PS passed. |
| New packaged worker | Complete 125-record Mail Merge inspection / 250 planned pages, two different Clean Fields nodes, 50-row paging, one-record preview, PDF step inspection and local PS profile import passed. No formal production output or approval occurred during checks. |
| Installation | QA-only installer installed the same payload, ran production acceptance and uninstalled. No user PDF handlers or shortcuts were registered; the user's existing installation was not modified. |
| Upgrade | Actual 3.0.0 and 3.0.1 binaries with the current source supervisor, scripted restart and signed update passed. State: current=3.0.1, previous=3.0.0, phase=stable; isolated user-data sentinel preserved. This is not a manual updater-UI test. |
| Integrity | Ed25519 manifest signature, all three download SHA256 files, ZIP versions and source fingerprints verified. No private signing key was packaged. |

Payload source fingerprint:
`7bac29ff396a6a55fb5393d816f4820c37bd00ef5745573954ccc56c3f6db5fd`.
Documentation/test-only follow-ups do not change this application payload.

| Download suffix | Bytes | SHA256 |
| --- | ---: | --- |
| Update-Windows-x64.zip | 351591241 | `f7d1a72b1474f78075ee7f5aa35f137577584e12db4e7f8c7b294d852f235d15` |
| Managed-Portable-Windows-x64.zip | 364563259 | `8435c03218a48ff182cee514b6916c46e339d6113b7142256c88337b9e09996b` |
| Setup-Windows-x64.exe | 242742360 | `d6e85c138d36264c6c368d3af0f32963cb79918b3b3da4b547fa36e479dd1ed5` |

Full download prefix: `PDFDocuEdit-Pro-v3.0.1-`. Local evidence is retained under
`build/release-3.0.1-validation/` (frozen-200, worker, upgrade, artifacts.json and
CI benchmarks) and `build/composition-install-qa/result.json`.

## Intentional test contract update

`test_release_metadata_is_v3_0_1` replaces the historical version assertion and
checks application, project, build and installer metadata consistently at 3.0.1.
No existing Windows regression cases are removed or disabled.

The shortcut-customization module uses the shared QApplication/theme fixture and
explicitly closes/releases its native widgets before application teardown.
Initial CI showed an intermittent post-assertion Windows access violation, even
though all three assertions passed; its failure remains in the CI history. New
runs retain raw UI logs/JUnit and enable native faulthandler diagnostics. No
assertions are changed and crashes remain failures.

Real printer paper selection and inserter acceptance remain outside automated
software validation and require device tests by the operator.
