"""Private, subject-bound Chromium snapshots, separate from clean-home goldens.

The program also runs over SSH with the host's standard-library Python. Only
metadata leaves the host; neither the archive nor profile contents are output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import subprocess
import tarfile
import tempfile

from yoke_harness.browser_profile_archive_validation import (
    CAPTURE_RECOVERY,
    ProfileArchiveError,
    archive_step,
    digest,
    identity,
    sync_snapshot,
    literal_path,
    no_symlink_parents,
    private_owned,
    require,
)
from yoke_harness.browser_profile_writer_inventory import WRITER_INVENTORY_PROGRAM
from yoke_contracts.machine_config.directories import create_private_directory


ARCHIVE_NAME = "profile.tar.gz"
MANIFEST_NAME = "manifest.json"
TRANSIENT_NAMES = frozenset({"SingletonLock", "SingletonCookie", "SingletonSocket"})
MAX_ARCHIVE_BYTES = 2 * 1024**3
MAX_ARCHIVE_MEMBERS = 100_000


def capture_parent_owned(path: Path) -> None:
    """A readable golden parent is safe; other users must not replace snapshots."""
    info = path.lstat()
    if info.st_uid != os.getuid() or not stat.S_ISDIR(info.st_mode):
        raise ProfileArchiveError("browser_profile_parent_unsafe", path=path)
    if info.st_mode & 0o022:
        raise ProfileArchiveError("browser_profile_parent_writable", path=path)


def profile_writers_absent(profile: Path) -> None:
    """Read protected same-user descriptors; never elevate archive writes."""
    try:
        result = subprocess.run(
            (
                [sys.executable]
                if sys.platform == "darwin"
                else ["sudo", "-n", "/usr/bin/python3"]
            )
            + [
                "-c",
                WRITER_INVENTORY_PROGRAM,
                str(os.getuid()),
                str(profile),
                str(os.getpid()),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        evidence = json.loads(result.stdout)
        if not isinstance(evidence, dict):
            raise ValueError("inventory must return a verdict")
    except (OSError, ValueError, subprocess.SubprocessError):
        raise ProfileArchiveError(
            "browser_profile_writer_inventory_unavailable"
        ) from None
    require(
        result.returncode == 0 and evidence.get("ok") is True,
        evidence.get("reason", "browser_profile_writer_inventory_unavailable"),
    )


def profile_inventory(profile: Path) -> dict[str, tuple]:
    private_owned(profile, directory=True)
    inventory = {}
    for root, directories, files in os.walk(profile, followlinks=False):
        for name in [*directories, *files]:
            path = Path(root) / name
            relative = path.relative_to(profile)
            info = path.lstat()
            if len(relative.parts) == 1 and name in TRANSIENT_NAMES:
                if name in directories:
                    directories.remove(name)
                continue
            require(info.st_uid == os.getuid(), "browser_profile_foreign_owner")
            require(
                stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode),
                "browser_profile_unsafe_entry",
            )
            require(
                not stat.S_ISREG(info.st_mode) or info.st_nlink == 1,
                "browser_profile_hardlink",
            )
            inventory[str(relative)] = (
                info.st_ino,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
                stat.S_ISDIR(info.st_mode),
            )
    require(any(not value[-1] for value in inventory.values()), "browser_profile_empty")
    return inventory


def archive_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    require(0 < len(members) <= MAX_ARCHIVE_MEMBERS, "browser_profile_archive_invalid")
    names = set()
    total = 0
    for member in members:
        path = PurePosixPath(member.name)
        require(
            not path.is_absolute()
            and ".." not in path.parts
            and str(path) == member.name
            and member.name not in names
            and member.name not in {".", ""}
            and (member.isdir() or member.isfile()),
            "browser_profile_archive_unsafe",
        )
        require(
            not member.isfile() or member.size >= 0, "browser_profile_archive_invalid"
        )
        names.add(member.name)
        total += member.size
    require(total <= MAX_ARCHIVE_BYTES, "browser_profile_archive_too_large")
    return members


def validate_snapshot_pair(baseline: Path, subject: dict) -> tuple[dict, dict]:
    """Read back the sealed pair without trusting the write-side receipt."""
    with archive_step("permission"):
        private_owned(baseline, directory=True)
        for name in (ARCHIVE_NAME, MANIFEST_NAME):
            private_owned(baseline / name)
    with archive_step("manifest_read"):
        require(
            (baseline / MANIFEST_NAME).stat().st_size > 0,
            "browser_profile_manifest_empty",
            recovery=CAPTURE_RECOVERY,
        )
        manifest_text = (baseline / MANIFEST_NAME).read_text(encoding="utf-8")
    with archive_step("manifest_parse"):
        manifest = json.loads(manifest_text)
    with archive_step("archive_read"):
        require(
            (baseline / ARCHIVE_NAME).stat().st_size > 0,
            "browser_profile_archive_empty",
            recovery=CAPTURE_RECOVERY,
        )
        archive_digest = digest(baseline / ARCHIVE_NAME)
    require(
        manifest == {**subject, "sha256": archive_digest},
        "browser_profile_baseline_identity_mismatch",
    )
    with archive_step("archive_open"):
        archive = tarfile.open(baseline / ARCHIVE_NAME, "r:gz")
    with archive_step("archive_read"), archive:
        members = archive_members(archive)
        require(
            any(member.isfile() for member in members),
            "browser_profile_archive_no_files",
            recovery=CAPTURE_RECOVERY,
        )
        return manifest, {
            member.name: (member.size, member.isdir()) for member in members
        }


def capture(home: Path, baseline: Path, project: str, relative: str) -> dict:
    subject = identity(home, project, relative)
    profile = home / relative
    no_symlink_parents(profile)
    no_symlink_parents(baseline)
    require(
        baseline != home and home not in baseline.parents,
        "browser_profile_baseline_inside_home",
    )
    require(not baseline.exists(), "browser_profile_destination_occupied")
    create_private_directory(baseline.parent)
    capture_parent_owned(baseline.parent)
    profile_writers_absent(profile)
    with archive_step("capture_source"):
        before = profile_inventory(profile)
    temporary = Path(tempfile.mkdtemp(prefix=".browser-profile-", dir=baseline.parent))
    try:
        private_owned(temporary, directory=True)
        with tarfile.open(temporary / ARCHIVE_NAME, "w:gz") as archive:
            for name in sorted(before):
                member = archive.gettarinfo(str(profile / name), arcname=name)
                member.uid = member.gid = os.getuid()
                member.uname = member.gname = ""
                member.mode = 0o700 if member.isdir() else 0o600
                if member.isfile():
                    with (profile / name).open("rb") as stream:
                        archive.addfile(member, stream)
                else:
                    archive.addfile(member)
        os.chmod(temporary / ARCHIVE_NAME, 0o600)
        profile_writers_absent(profile)
        require(
            before == profile_inventory(profile),
            "browser_profile_changed_during_capture",
        )
        with archive_step("archive_read"):
            manifest = {**subject, "sha256": digest(temporary / ARCHIVE_NAME)}
        with archive_step("manifest_write"):
            (temporary / MANIFEST_NAME).write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            os.chmod(temporary / MANIFEST_NAME, 0o600)
        with archive_step("capture_seal"):
            sync_snapshot(temporary, (ARCHIVE_NAME, MANIFEST_NAME))
            _, members = validate_snapshot_pair(temporary, subject)
            expected = {
                name: (0 if entry[-1] else entry[1], entry[-1])
                for name, entry in before.items()
            }
            require(
                members == expected,
                "browser_profile_archive_profile_mismatch",
                recovery=CAPTURE_RECOVERY,
            )
            temporary.rename(baseline)
            sync_snapshot(baseline.parent, ())
            manifest, members = validate_snapshot_pair(baseline, subject)
            require(
                members == expected,
                "browser_profile_archive_profile_mismatch",
                recovery=CAPTURE_RECOVERY,
            )
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {
        "ok": True,
        "capture_component": "browser-profile",
        "sealed": True,
        "browser_profile_baseline_path": str(baseline),
        "manifest_digest": hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode()
        ).hexdigest(),
    }


def restore(home: Path, baseline: Path, project: str, relative: str) -> dict:
    subject = identity(home, project, relative)
    profile = home / relative
    no_symlink_parents(profile)
    no_symlink_parents(baseline)
    require(
        baseline != home and home not in baseline.parents,
        "browser_profile_baseline_inside_home",
    )
    validate_snapshot_pair(baseline, subject)
    # Restoring a profile is explicitly an installed-product fixture, never a
    # fresh-home baseline operation. The fixture invokes the launcher's Python.
    require((home / ".yoke").is_dir(), "browser_profile_requires_installed_yoke")
    require(not profile.exists(), "browser_profile_destination_occupied")
    profile_writers_absent(profile)
    with archive_step("extraction"):
        create_private_directory(profile.parent)
        private_owned(profile.parent, directory=True)
        temporary = Path(
            tempfile.mkdtemp(prefix=".browser-profile-", dir=profile.parent)
        )
        try:
            with archive_step("archive_open"):
                archive = tarfile.open(baseline / ARCHIVE_NAME, "r:gz")
            with archive, archive_step("extraction"):
                members = archive_members(archive)
                for member in sorted(
                    members,
                    key=lambda entry: (
                        len(PurePosixPath(entry.name).parts),
                        entry.name,
                    ),
                ):
                    target = temporary / member.name
                    create_private_directory(target.parent)
                    if member.isdir():
                        create_private_directory(target)
                    else:
                        with (
                            archive.extractfile(member) as source,
                            target.open("xb") as output,
                        ):
                            shutil.copyfileobj(source, output)
                        os.chmod(target, 0o600)
            profile_writers_absent(profile)
            temporary.rename(profile)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    return {"ok": True, "restored": True, "project": project}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("capture", "restore"))
    parser.add_argument("home")
    parser.add_argument("baseline")
    parser.add_argument("project")
    parser.add_argument("profile_relative_path")
    args = parser.parse_args()
    try:
        result = {"capture": capture, "restore": restore}[args.operation](
            literal_path(args.home),
            literal_path(args.baseline),
            args.project,
            args.profile_relative_path,
        )
    except ProfileArchiveError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "reason": str(exc),
                    **exc.details,
                    **({"unsafe_path": str(exc.path)} if exc.path is not None else {}),
                }
            )
        )
        return 1
    except (OSError, ValueError, tarfile.TarError):
        print(json.dumps({"ok": False, "reason": "browser_profile_archive_refused"}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
