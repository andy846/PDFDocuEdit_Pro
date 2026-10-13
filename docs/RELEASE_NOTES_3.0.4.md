# PDFDocuEdit Pro v3.0.4

## Windows x64 — account-enabled production version

- Existing v3.0.3 Managed installations can update to the account-enabled
  editor without replacing their launcher. Subsequent upgrades remain supported.
- New installs include a production-branded managed installer/portable package.
- First sign-in requires an approved online account. Saved approval supports
  offline use; account status and sign-out are in Settings/More commands.
- Restore the startup splash, with the version rendered from app metadata.
- Signed updates preserve save/cancel handling and startup rollback.

## macOS Apple Silicon — account-enabled testing version

- Managed DMG with Keychain account approval and platform-bound signed updates.
- The same account/recovery policy as Windows; fixed application launcher and
  user-owned version/settings storage.
- macOS 13+, Apple Silicon only. This build is ad-hoc signed and NOT Apple
  notarized. Initial launch may require explicit system approval.
- Intel, OCR and production-printer/DFE parity remain outside this release.

## Updating

Use Help / Check for Updates, download, save work, then Update and Restart.
Windows upgrades require an approved account after restart; arrange accounts
before deployment. Mac users install the Managed DMG for automatic updates.
Template/workflow formats and the update trust key are unchanged.

Publication requires passing the native and operator gates in UNIFIED_RELEASE.md.
