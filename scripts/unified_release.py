"""Validate native candidates, sign on the owner machine, publish one draft."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

from scripts.release_signing import load_signing_key, write_update_metadata
from updates.protocol import Manifest, UpdateError, archive_members, atomic_json, digest_file, version
from updates.target import DEFAULT_TARGET, UpdateTarget
from updates.trust import PUBLIC_KEY_HEX, REPOSITORY


def validate_candidates(folder, expected_version, expected_commit):
    folder = Path(folder)
    version(expected_version)
    if len(expected_commit) != 40 or any(c not in "0123456789abcdef" for c in expected_commit):
        raise UpdateError("Specify the frozen 40-character source commit.")
    projects, fingerprints, records = set(), set(), []
    for platform in ("windows-x64", "macos-arm64"):
        data = json.loads((folder / f"candidate-{platform}.json").read_text(encoding="utf-8"))
        if (data.get("version"), data.get("source_commit"), data.get("platform"), data.get("channel")) != (
            expected_version, expected_commit, platform, "private"
        ):
            raise UpdateError("Both platforms must have the same committed account release version.")
        target = UpdateTarget(platform, "private", data["auth_project"])
        projects.add(target.auth_project)
        fingerprints.add(data["source_fingerprint"])
        fingerprint = data["source_fingerprint"]
        if len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint):
            raise UpdateError("Native source fingerprint is invalid.")
        checks = data["checks"]
        regression = checks.get("regression", {})
        login = checks.get("frozen_login", {})
        login_passed = (login.get("accepted_before_login") is True and login.get("real_frozen_launcher") is True
                        if platform == "windows-x64" else
                        login.get("login_shell_started") is True and login.get("managed_handshake") is True
                        and login.get("unauthenticated_entries_blocked") is True)
        if (checks.get("native_packaging") is not True or regression.get("passed") is not True or not login_passed
                or regression.get("modules", 0) <= 0 or regression.get("tests", 0) <= 0):
            raise UpdateError("Native packaging, regression and frozen login gates must pass.")
        names = set()
        for row in data["files"]:
            name = row["name"]
            if not isinstance(name, str) or Path(name).name != name or name in names or "/" in name or "\\" in name:
                raise UpdateError("Candidate attachment names must be unique flat filenames.")
            names.add(name)
            path = folder / name
            if path.is_symlink() or path.stat().st_size != row["size"] or digest_file(path) != row["sha256"]:
                raise UpdateError(f"Candidate attachment changed: {name}")
        required = {target.asset(expected_version), f"candidate-{target.metadata}.json"}
        if platform == "windows-x64":
            required |= {DEFAULT_TARGET.asset(expected_version), "candidate-update.json",
                         f"PDFDocuEdit-Pro-v{expected_version}-Managed-Portable-Windows-x64-Private.zip",
                         f"PDFDocuEdit-Pro-v{expected_version}-Setup-Windows-x64.exe"}
        else:
            required.add(f"PDFDocuEdit-Pro-v{expected_version}-Managed-macOS-arm64-Private.dmg")
        if not required <= names:
            raise UpdateError(f"Required {platform} attachments are missing.")
        with zipfile.ZipFile(folder / target.asset(expected_version)) as archive:
            prefix = "_internal/" if platform == "windows-x64" else "PDFDocuEdit Pro.app/Contents/Resources/"
            identity = json.loads(archive.read(prefix + "update-target.json"))
            build = json.loads(archive.read(prefix + "update_build.json"))
        if identity != {"platform": platform, "channel": "private", "auth_project": target.auth_project}:
            raise UpdateError("Embedded application update identity differs.")
        if (build.get("source_commit"), build.get("version"), build.get("source_fingerprint")) != (
            expected_commit, expected_version, fingerprint
        ):
            raise UpdateError("Packaged application provenance differs from native evidence.")
        records.append(data)
    if len(projects) != 1 or len(fingerprints) != 1:
        raise UpdateError("Platform account projects or source fingerprints differ.")
    return records


def seal(folder, output, app_version, commit, key):
    folder, output = Path(folder), Path(output)
    records = validate_candidates(folder, app_version, commit)
    if output.exists():
        raise UpdateError("Use a fresh signing output directory; never overwrite signed release assets.")
    output.mkdir(parents=True)
    targets = [DEFAULT_TARGET, UpdateTarget("windows-x64", "private", records[0]["auth_project"]),
               UpdateTarget("macos-arm64", "private", records[0]["auth_project"])]
    names = []
    try:
        for record in records:
            for row in record["files"]:
                if not row["name"].startswith("candidate-"):
                    shutil.copyfile(folder / row["name"], output / row["name"])
                    names.append(row["name"])
        for target in targets:
            data = json.loads((folder / f"candidate-{target.metadata}.json").read_text(encoding="utf-8"))
            expected_app = UpdateTarget(target.platform, "private", records[0]["auth_project"])
            # Verify candidates before the owner signs them, using a throwaway
            # key solely to run the SAME production manifest/archive validator.
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            temporary = Ed25519PrivateKey.generate()
            raw = json.dumps(data, sort_keys=True, indent=2).encode()
            manifest = Manifest.verify(raw, temporary.sign(raw), temporary.public_key().public_bytes_raw().hex(),
                                       target=target, application_target=expected_app)
            if manifest.version != app_version:
                raise UpdateError("Candidate manifest version differs from its native evidence.")
            manifest.verify_archive(output / manifest.asset)
            with zipfile.ZipFile(output / manifest.asset) as archive:
                if target.platform == "windows-x64":
                    archive_members(archive, manifest.expanded_size)
                else:
                    from updates.macos_archive import bundle_members
                    bundle_members(archive, manifest.expanded_size)
            if target.platform == "macos-arm64" and manifest.maturity != "preview":
                raise UpdateError("Unnotarized first Mac release must be marked preview.")
            metadata, signature = write_update_metadata(output, data, key)
            names.extend([metadata.name, signature.name])
        if digest_file(output / targets[0].asset(app_version)) != digest_file(output / targets[1].asset(app_version)):
            raise UpdateError("Legacy and private Windows packages must be identical.")
        index = {"schema": 1, "version": app_version, "source_commit": commit, "auth_project": records[0]["auth_project"],
                 "platforms": ["windows-x64", "macos-arm64"], "native_evidence": records,
                 "files": [{"name": name, "size": (output / name).stat().st_size, "sha256": digest_file(output / name)}
                           for name in sorted(set(names))]}
        atomic_json(output / "release-index.json", index)
        (output / "release-index.sig").write_bytes(key.sign((output / "release-index.json").read_bytes()))
    except Exception:
        # Keep failed artifacts for diagnosis; absence of a signed index prevents publication.
        (output / "release-index.json").unlink(missing_ok=True)
        (output / "release-index.sig").unlink(missing_ok=True)
        raise
    return index


def validate_sealed(folder):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    folder = Path(folder)
    raw = (folder / "release-index.json").read_bytes()
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY_HEX)).verify(
            (folder / "release-index.sig").read_bytes(), raw)
    except Exception as error:
        raise UpdateError("Release index signature is invalid.") from error
    data = json.loads(raw)
    for row in data["files"]:
        name = row["name"]
        if Path(name).name != name or "/" in name or "\\" in name:
            raise UpdateError("Invalid release attachment path.")
        path = folder / name
        if path.is_symlink() or path.stat().st_size != row["size"] or digest_file(path) != row["sha256"]:
            raise UpdateError(f"Signed release attachment differs: {name}")
    return data


def find_release(tag):
    # /releases/tags/{tag} retrieves published releases and returns 404 for
    # drafts, even to the owner. The authenticated list includes drafts.
    result = subprocess.run(["gh", "api", "--paginate", f"repos/{REPOSITORY}/releases?per_page=100",
                             "--jq", f'.[] | select(.tag_name == {json.dumps(tag)}) | .id'],
                            capture_output=True, text=True, encoding="utf-8", check=False)
    if result.returncode:
        raise UpdateError("Cannot verify existing releases; no draft was created.")
    ids = result.stdout.split()
    if len(ids) > 1 or any(not item.isdigit() for item in ids):
        raise UpdateError("Release tag lookup is ambiguous.")
    if not ids:
        return None
    return json.loads(subprocess.check_output(["gh", "api", f"repos/{REPOSITORY}/releases/{ids[0]}"], text=True, encoding="utf-8"))


def publish(folder, notes, *, make_public=False):
    folder = Path(folder)
    data = validate_sealed(folder)
    tag = "v" + data["version"]
    release = find_release(tag)
    if release is not None:
        if not release["draft"]:
            raise UpdateError("A published release is immutable. Use a new version.")
        if release["target_commitish"] != data["source_commit"]:
            raise UpdateError("Existing draft source commit differs.")
    else:
        subprocess.run(["gh", "release", "create", tag, "--repo", REPOSITORY, "--draft",
                        "--target", data["source_commit"], "--title", f"PDFDocuEdit Pro {tag}",
                        "--notes-file", str(notes)], check=True)
    release = find_release(tag)
    if release is None:
        raise UpdateError("Created draft could not be verified.")
    args = ["gh", "api", f"repos/{REPOSITORY}/releases/{release['id']}"]
    names = [row["name"] for row in data["files"]] + ["release-index.json", "release-index.sig"]
    rows = {row["name"]: row for row in data["files"]}
    for name in ("release-index.json", "release-index.sig"):
        rows[name] = {"sha256": digest_file(folder / name), "size": (folder / name).stat().st_size}
    remote = {row["name"]: row for row in release["assets"]}
    if set(remote) - set(names):
        raise UpdateError("Draft contains unexpected attachments.")
    for name in names:
        if name in remote:
            digest = remote[name].get("digest", "")
            if digest != "sha256:" + rows[name]["sha256"] or remote[name]["size"] != rows[name]["size"]:
                raise UpdateError("An existing draft attachment differs; it will not be overwritten.")
            continue
        subprocess.run(["gh", "release", "upload", tag, str(folder / name), "--repo", REPOSITORY], check=True)
    release = json.loads(subprocess.check_output(args, text=True, encoding="utf-8"))
    remote = {row["name"]: row for row in release["assets"]}
    if set(remote) != set(names) or any(remote[name].get("digest") != "sha256:" + rows[name]["sha256"]
                                      or remote[name]["size"] != rows[name]["size"] for name in names):
        raise UpdateError("Uploaded draft attachments have not all been verified.")
    if make_public:
        acceptance = folder / "operator-acceptance.json"
        if not acceptance.is_file():
            raise UpdateError("Real operator acceptance is missing; release remains a draft.")
        approval = json.loads(acceptance.read_text(encoding="utf-8"))
        required = ("windows_two_upgrades", "windows_account_login", "mac_account_login", "mac_offline_restart", "mac_cross_version_update")
        if approval.get("source_commit") != data["source_commit"] or not all(approval.get(item) is True for item in required):
            raise UpdateError("Operator acceptance is incomplete; release remains a draft.")
        subprocess.run(["gh", "release", "edit", tag, "--repo", REPOSITORY, "--draft=false", "--prerelease=false", "--latest"], check=True)
    return release["html_url"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    signing = sub.add_parser("seal")
    signing.add_argument("--candidates", type=Path, required=True)
    signing.add_argument("--output", type=Path, required=True)
    signing.add_argument("--version", required=True)
    signing.add_argument("--commit", required=True)
    signing.add_argument("--key", type=Path, required=True)
    publication = sub.add_parser("publish")
    publication.add_argument("--folder", type=Path, required=True)
    publication.add_argument("--notes", type=Path, required=True)
    publication.add_argument("--make-public", action="store_true")
    args = parser.parse_args()
    if args.command == "seal":
        seal(args.candidates, args.output, args.version, args.commit, load_signing_key(args.key))
    else:
        print(publish(args.folder, args.notes, make_public=args.make_public))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
