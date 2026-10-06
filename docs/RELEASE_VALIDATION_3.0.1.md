# v3.0.1 release validation

Release preparation started 2026-10-06 on Windows x64 / Python 3.12.
Publication requires passing CI and final packaged acceptance. This record will
be updated with actual results; pending steps are not claimed as passed.

## Completed development checks

- 79 targeted Workflow tests passed; 9 CI-scope tests passed; Ruff passed.
- 960×640 at 200% scale: light/dark node settings and paginated results inspected.
- In-app README construction test passed after the documentation update.

## Release gates

- Full GitHub PR/tag CI: pending.
- Fresh PyInstaller, managed Launcher, signed Update/Managed Portable, Setup: pending.
- Frozen production acceptance and isolated 3.0.0 → 3.0.1 update: pending.
- Published assets, checksums and signed manifest verification: pending.

## Intentional test contract update

`test_release_metadata_is_v3_0_1` replaces the historical version assertion and
checks application, project, build and installer metadata consistently at 3.0.1.
No existing Windows regression cases are removed or disabled.

Real printer paper selection and inserter acceptance remain outside automated
software validation and require device tests by the operator.
