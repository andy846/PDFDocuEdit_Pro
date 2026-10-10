# v3.0.4 Windows / macOS account release

Windows x64 is the production target. Apple Silicon macOS 13+ is an
unnotarized testing target. Both require the same approved account project.
This document is an operating procedure, not evidence that publication or
real-account/operator acceptance has passed.

## Existing installations

- v3.0.3 Windows Managed users keep their frozen Launcher.exe. Its SHA256 is
  allowlisted in updates/target.py. It receives update.json/update.sig and the
  original Windows update filename. The identical account application is also
  published through the schema-2 private channel.
- The new editor resolves transport from the installed launcher, then checks
  the signed application_target. An unknown launcher, missing identity, another
  project, or a non-account payload is blocked. The legacy compatibility assets
  must remain in EVERY subsequent release, including upgrades skipped by users.
- New account launchers use platform/private manifests. Mac standalone users
  install the matching Managed DMG once; the signed outer launcher remains in
  Applications and versions/settings remain in user-owned Application Support.
- Login approval is in the OS credential store, outside update rollback.
  Login readiness confirms startup; missing credentials/password mistakes are
  not installation failures. First login requires an approved online account.

## Build once from committed source

The workflow **Unified account release candidates** builds both native targets
from the same SHA. Windows reuses only native dependencies from the signed
v3.0.3 payload; current source/runtime validators still check them.
It runs the complete isolated Windows suite and the native Mac release plan.

Intentional regression-suite maintenance for this release: source metadata
assertions now require v3.0.4 across all build inputs; legacy UI tests use the
existing session QApplication fixture to prevent Qt teardown/recreation
between test cases. No test is disabled or filtered to satisfy these gates.

Artifacts contain release-candidate files and candidate-<platform>.json.
The latter records commit, source fingerprint, account project, native checks,
and exact attachment hashes. No update private key or real account credentials
are supplied to hosted runners. Mac candidates retain ad-hoc bundle signing and
are explicitly marked preview in their signed update metadata.

Download both artifacts from the SAME workflow run and merge their
release-candidate folders into one fresh local candidates directory.
Never add arbitrary files or sign output from a different commit.
The release tooling on the controlled signing machine can receive fixes after
application source is frozen. Pass the native artifacts' frozen application SHA
explicitly; never relabel packages as the newer tooling SHA. Both application
packages still must match each other and their actual embedded provenance.

## Sign on the owner's controlled machine

```text
python -m scripts.unified_release seal --candidates build/candidates --output release-sealed/v3.0.4 --version 3.0.4 --commit FULL_FROZEN_COMMIT --key OUTSIDE_REPOSITORY/signing.pem
```

The existing Ed25519 trust anchor is retained. An encrypted key uses a hidden
password prompt, never an argument/env var. The signer verifies both native
indexes, package provenance, identities, file hashes and update metadata.
It writes signed platform manifests, the legacy compatibility manifest,
release-index.json and release-index.sig. A fresh output directory is required.
Unsigned candidate JSON files are NOT public update manifests.

## Create and verify one GitHub draft

```text
python -m scripts.unified_release publish --folder release-sealed/v3.0.4 --notes docs/RELEASE_NOTES_3.0.4.md
```

Only indexed attachments are uploaded. Existing public releases cannot be
modified. An interrupted draft upload can be resumed only when existing asset
hashes match; no --clobber is used. Missing/mismatched assets leave the draft.

Before public promotion, put operator-acceptance.json in the sealed folder:

```json
{
  "source_commit": "FULL_FROZEN_COMMIT",
  "windows_two_upgrades": true,
  "windows_account_login": true,
  "mac_account_login": true,
  "mac_offline_restart": true,
  "mac_cross_version_update": true
}
```

Record true ONLY after the corresponding actual test, and retain its evidence
under build. The Windows gate must use the ORIGINAL frozen v3.0.3 launcher,
not the current source supervisor, and two different newer frozen editor
versions. A synthetic follow-on version is QA only and is never uploaded.
Use the isolated frozen-launcher gate with the original deployment ZIP and
two signed compatibility updates whose embedded editor versions actually differ:

```text
python -m scripts.legacy_upgrade_smoke --baseline ORIGINAL_V303_MANAGED_PORTABLE.zip --updates SIGNED_V304_FOLDER SIGNED_QA_FOLLOW_ON_FOLDER --output build/fresh-legacy-upgrade-test
```

The gate starts only its own empty offscreen QA application, verifies each
startup handshake, unchanged launcher and retained settings, and writes
result.json. It never drives or terminates the operator's existing application.
The Mac gates require an operator Mac/account; hosted synthetic tests do not
count as real-account login or offline use.

Use a short QA output path on Windows. The unchanged original launcher remains
subject to the installed OS/Python path limits; deep native dependency paths
can exceed MAX_PATH under a long worktree directory. The helper checks this
before starting its frozen test application. A long-path installed deployment
may require reinstalling in a shorter managed directory; no global OS setting
is changed by this release.

### Existing Mac v3.0.3 account testing installation

A draft is not visible to the installed app's normal latest-release check.
Before publication, use the operator-only candidate helper to test the existing
installation with the signed Mac package. This uses the existing transaction,
settings backup, native bundle validation, readiness handshake and rollback
supervisor; it does not replace the fixed installed launcher.

1. Save work and close PDFDocuEdit Pro on the Apple Silicon Mac.
2. Put the signed Mac update ZIP and its matching platform `.json` / `.sig`
   from the sealed draft into one directory. Do not use `candidate-*.json`.
3. Use a checkout containing the owner helper and Python 3.12 with the
   `cryptography` dependency (the helper does not require Qt or account secrets).
4. Run from that checkout:

```text
python3 -m scripts.macos_candidate_upgrade --app "/Applications/PDFDocuEdit Pro.app" --folder "$HOME/Downloads/v3.0.4-update" --report "$HOME/Desktop/mac-update-result.json"
```

Keep Terminal open until the upgraded app is closed. An already running app,
pending update, wrong project/platform, invalid signature or damaged ZIP blocks
the operation. Existing pending work is left untouched. Close the app normally
after testing; the report records the actual version transition, not a claim
that account login was tested. Reopen the installed app normally to confirm it
still launches v3.0.4, then test approved account login and offline reopening.
Provide the report and those two operator results before public promotion.
Do not set acceptance flags solely because the helper's synthetic tests passed.

```text
python -m scripts.unified_release publish --folder release-sealed/v3.0.4 --notes docs/RELEASE_NOTES_3.0.4.md --make-public
```

The unified Release uses a stable version/tag so existing Windows latest-release
checks work. Its Mac attachments/UI are individually labelled testing/preview.
No automatic forced install is introduced. Published assets are immutable;
repairs use a higher patch version and a new frozen commit.

## Acceptance

Verify wrong platform/project, tampered manifest/ZIP, missing attachments,
download cancellation, cancelled save, rollback and retained project paths.
Also test actual account sign-in, saved offline approval, revoked access and
secure-store permission prompts following an update.
Mac Gatekeeper may require explicit operator approval for this unnotarized
build. Do not disable Gatekeeper globally. Developer ID/notarization is a
separate gate before claiming a public production-quality Mac installation.
