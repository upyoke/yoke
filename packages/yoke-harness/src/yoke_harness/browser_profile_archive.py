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
import tarfile
import tempfile


ARCHIVE_NAME = "profile.tar.gz"
MANIFEST_NAME = "manifest.json"
TRANSIENT_NAMES = frozenset({"SingletonLock", "SingletonCookie", "SingletonSocket"})
MAX_ARCHIVE_BYTES = 2 * 1024**3
MAX_ARCHIVE_MEMBERS = 100_000


class ProfileArchiveError(ValueError):
    """A snapshot cannot be safely captured or restored."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ProfileArchiveError(code)


def private_owned(path: Path, *, directory: bool = False) -> None:
    info = path.lstat()
    require(info.st_uid == os.getuid(), "browser_profile_foreign_owner")
    require(not info.st_mode & 0o077, "browser_profile_not_private")
    require(
        stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode),
        "browser_profile_unsafe_entry",
    )


def literal_path(value: str) -> Path:
    selected = Path(value)
    require(
        selected.is_absolute()
        and str(selected) == value
        and ".." not in selected.parts
        and len(selected.parts) >= 3,
        "browser_profile_unsafe_path",
    )
    return selected


def no_symlink_parents(path: Path) -> None:
    for parent in (path, *path.parents):
        require(not parent.is_symlink(), "browser_profile_symlink_path")


def profile_writers_absent(profile: Path) -> None:
    """Refuse active Chromium writers without terminating any process."""
    proc = Path("/proc")
    require(proc.is_dir(), "browser_profile_os_unsupported")
    for process in proc.iterdir():
        if not process.name.isdigit() or process.name == str(os.getpid()):
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            command = (process / "cmdline").read_bytes()
            require(
                os.fsencode(profile) not in command, "browser_profile_writer_active"
            )
            for fd in (process / "fd").iterdir():
                try:
                    target = Path(os.readlink(fd).removesuffix(" (deleted)"))
                except FileNotFoundError:
                    continue
                require(
                    target != profile and profile not in target.parents,
                    "browser_profile_writer_active",
                )
        except FileNotFoundError:
            continue
        except PermissionError:
            raise ProfileArchiveError(
                "browser_profile_writer_inventory_unavailable"
            ) from None


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def identity(home: Path, project: str, relative: str) -> dict:
    selected = PurePosixPath(relative)
    require(
        not selected.is_absolute()
        and ".." not in selected.parts
        and str(selected) == relative
        and len(selected.parts) >= 3,
        "browser_profile_unsafe_path",
    )
    require(
        project
        and all(c.isascii() and (c.isalnum() or c in "._-") for c in project)
        and project not in {".", ".."},
        "browser_profile_project_invalid",
    )
    return {
        "home": str(home),
        "uid": os.getuid(),
        "project": project,
        "profile_relative_path": relative,
        "os": "linux",
    }


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
    baseline.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_owned(baseline.parent, directory=True)
    profile_writers_absent(profile)
    before = profile_inventory(profile)
    temporary = Path(tempfile.mkdtemp(prefix=".browser-profile-", dir=baseline.parent))
    try:
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
        with tarfile.open(temporary / ARCHIVE_NAME, "r:gz") as archive:
            archive_members(archive)
        manifest = {**subject, "sha256": digest(temporary / ARCHIVE_NAME)}
        (temporary / MANIFEST_NAME).write_text(json.dumps(manifest))
        os.chmod(temporary / MANIFEST_NAME, 0o600)
        temporary.rename(baseline)
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
    private_owned(baseline, directory=True)
    for name in (ARCHIVE_NAME, MANIFEST_NAME):
        private_owned(baseline / name)
    manifest = json.loads((baseline / MANIFEST_NAME).read_text())
    require(
        manifest == {**subject, "sha256": digest(baseline / ARCHIVE_NAME)},
        "browser_profile_baseline_identity_mismatch",
    )
    # Restoring a profile is explicitly an installed-product fixture, never a
    # fresh-home baseline operation. The fixture invokes the launcher's Python.
    require((home / ".yoke").is_dir(), "browser_profile_requires_installed_yoke")
    require(not profile.exists(), "browser_profile_destination_occupied")
    profile_writers_absent(profile)
    with tarfile.open(baseline / ARCHIVE_NAME, "r:gz") as archive:
        archive_members(archive)
    profile.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_owned(profile.parent, directory=True)
    temporary = Path(tempfile.mkdtemp(prefix=".browser-profile-", dir=profile.parent))
    try:
        with tarfile.open(baseline / ARCHIVE_NAME, "r:gz") as archive:
            members = archive_members(archive)
            for member in sorted(
                members,
                key=lambda entry: (len(PurePosixPath(entry.name).parts), entry.name),
            ):
                target = temporary / member.name
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                if member.isdir():
                    target.mkdir(mode=0o700, exist_ok=True)
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
        print(json.dumps({"ok": False, "reason": str(exc)}))
        return 1
    except (OSError, ValueError, tarfile.TarError):
        print(json.dumps({"ok": False, "reason": "browser_profile_archive_refused"}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
