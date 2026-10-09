# macOS account and managed-update parity

Development baseline: 3.0.3. This work is on `codex/macos-parity`; it does not
replace the production Windows checkout, bump the version, or publish a release.

## Shared behaviour

| Capability | Windows private build | macOS private build |
| --- | --- | --- |
| First login | Online verified Supabase identity + active own access row | Same client/controller/project |
| Saved approval | Windows Credential Manager | Explicit macOS Keychain backend |
| Offline use | Saved approval, no expiry | Same policy; approval saved separately on each computer |
| Revocation | Startup/10-minute background check; retained work and save recovery | Same controller and recovery UI |
| Account entry | Settings/More commands; signed-in email | Same entry and branded login |
| Updates | Fixed Launcher.exe + signed ZIP | Fixed .app shell + signed .app ZIP |
| Update validation | Signature, checksum, platform/channel/project | Same checks plus arm64 and strict bundle code-sign verification |
| Failed update | Startup trial, previous version/settings recovery | Same transaction/supervisor |

Public builds remain authentication-free. Private updates are not permitted to
install public builds or another project's private build. The existing public
Windows schema-1 release assets and installer flow retain their names/behaviour.
Other channels use signed schema-2 manifests. `update-target.json` is sealed into
the app, and the runtime target is baked into the frozen Python module.

The signing trust anchor is unchanged. Real release assets still require its
matching external private key. Unsigned CI candidates have `candidate-*.json`
and no trusted manifest signature, so they cannot be downloaded as trusted
automatic updates. No production signing key or real login token goes to CI.

## Mac installation and launch

Copy the **Managed** DMG's outer `PDFDocuEdit Pro.app` into Applications and open
that app. It is a stable lightweight launcher, not the versioned editor. It
forwards Finder open-file and activation events to the running application.

The first launch installs its sealed initial editor under:

```text
~/Library/Application Support/PDFDocuEditPro/managed/
  private-<project>-arm64/       # or public-public-arm64
    versions/<version>/PDFDocuEdit Pro.app
    state.json
    installation.json
    data/ backups/ staging/ logs/ requests/
```

Updates are written to this user-owned directory; the updater never edits the
running signed outer bundle or needs administrator rights. Direct Finder launch
of a marked versioned editor routes back to the fixed launcher. A missing or
wrong-channel fixed launcher is an error, not an unmanaged fallback.

The editor acknowledges startup after its login window is available; waiting
for a Keychain prompt or human login does not fail an update trial. A secure
approval is not copied in settings backups, so rollback does not restore a
revoked/sign-out approval. Network errors do not revoke saved offline access.

## Build and verification

Run on an arm64 Mac, Python 3.12, after preparing the existing native runtimes:

```sh
python -m pip install -r requirements-macos.txt -r requirements-dev.txt -r requirements-auth-macos.lock
PDFDOCUEDIT_BUILD_AUTH=1 python -m scripts.build --composition
python -m scripts.macos_private_smoke --app 'dist/PDFDocuEdit Pro.app' --output build/macos-private-acceptance
python -m scripts.build_macos_managed
```

The last command produces the private Managed DMG and candidate update ZIP.
For a trusted update, provide `--key /outside/repository/signing.pem` matching
the existing trust anchor. Encrypted keys use a hidden password prompt. The key
is never included in the .app/DMG/ZIP. Owner publication is a separate action.
Windows private signed packaging uses `scripts/update_release.py build
--private-auth`; it does not create a public installer or public update assets.

Mac CI preserves public frozen production smoke tests, then builds/checks the
private login shell and denied worker/QA entries, and builds both managed
deployments. Targeted source tests include native Keychain round-trip with a
unique synthetic service, safe framework-link extraction, real arm64 bundle
signing, signed update installation, rollback and successful commit. They never
read/change the operator's real session. The frozen private smoke refuses a Mac
account with an existing real approval rather than clearing it.

The native round-trip uses the CI account's actual Keychain. The service name is
unique and the synthetic entry is deleted afterwards. Neither product nor tests
change the operator's Keychain defaults or unlock it. This iteration uses
`scripts.macos_test_plan --auth-updates` to repeat affected source tests;
the complete Mac plan remains available without this flag for the merge gate.

## Remaining operator gates

CI does not prove real-account login, Keychain permissions after an actual
cross-version publisher update, Retina interaction, or printer/DFE behaviour.
On the operator's Mac, test the same account as Windows, offline restart,
wrong-password/revoked access, unsaved-work recovery, update restart cancellation,
and a newer correctly signed private release. No such newer public release is
created by this change. Same-version ZIPs cannot be installed as upgrades.

Internal candidates are ad-hoc signed. Public Gatekeeper acceptance needs the
owner's Developer ID and notarization profile. Existing build environment hooks
`PDFDOCUEDIT_CODESIGN_IDENTITY` / `PDFDOCUEDIT_NOTARY_PROFILE` apply; no certificate
or Apple credentials are embedded. Intel and OCR remain outside this Mac port.

See [private account rules](PRIVATE_AUTH.md) and [Mac port evidence](MACOS_PARITY.md).
