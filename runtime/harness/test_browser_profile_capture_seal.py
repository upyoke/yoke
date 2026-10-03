"""Capture success requires the written and published sealed pair to round-trip."""

import errno
import json
from pathlib import Path
import tarfile

import pytest

from yoke_harness import browser_profile_archive as archive
from yoke_harness import browser_profile_archive_validation as validation

RELATIVE = ".yoke/secrets/capability-secrets/project/browser-control/profile"


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "profile_writers_absent", lambda _: None)
    home = tmp_path / "home"
    profile = home / RELATIVE
    profile.mkdir(mode=0o700, parents=True)
    profile.parent.chmod(0o700)
    (profile / "Default").mkdir()
    (profile / "Default" / "proof").write_bytes(b"opaque")
    return home, profile, tmp_path / "goldens" / "profile"


def capture(source):
    home, _, baseline = source
    return archive.capture(home, baseline, "project", RELATIVE)


def test_capture_receipt_is_backed_by_parse_digest_and_exact_members(source):
    receipt = capture(source)
    home, profile, baseline = source
    manifest, members = archive.validate_snapshot_pair(
        baseline, archive.identity(home, "project", RELATIVE)
    )
    assert receipt["sealed"] is True
    assert manifest["sha256"] == archive.digest(baseline / archive.ARCHIVE_NAME)
    assert members == {"Default": (0, True), "Default/proof": (6, False)}
    assert (profile / "Default" / "proof").read_bytes() == b"opaque"


@pytest.mark.parametrize(
    "contents,reason",
    [
        ("", "browser_profile_manifest_empty"),
        ("not-json", "browser_profile_manifest_parse_failed"),
        ("{}", "browser_profile_baseline_identity_mismatch"),
    ],
)
def test_capture_refuses_written_empty_invalid_or_mismatched_manifest(
    source, monkeypatch, contents, reason
):
    original = Path.write_text

    def damage(path, text, *args, **kwargs):
        return original(
            path,
            contents if path.name == archive.MANIFEST_NAME else text,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(Path, "write_text", damage)
    with pytest.raises(archive.ProfileArchiveError, match=reason):
        capture(source)
    assert not source[2].exists()
    assert not list(source[2].parent.glob(".browser-profile-*"))
    assert (source[1] / "Default" / "proof").read_bytes() == b"opaque"


@pytest.mark.parametrize(
    "damage",
    ["empty_archive", "empty_manifest", "bad_archive", "bad_digest", "wrong_members"],
)
def test_capture_refuses_pair_damaged_when_published(source, monkeypatch, damage):
    original = Path.rename

    def publish(path, destination):
        result = original(path, destination)
        baseline = Path(destination)
        archive_path = baseline / archive.ARCHIVE_NAME
        manifest_path = baseline / archive.MANIFEST_NAME
        if damage == "empty_manifest":
            manifest_path.write_bytes(b"")
        elif damage == "empty_archive":
            archive_path.write_bytes(b"")
        else:
            if damage == "bad_archive":
                archive_path.write_bytes(b"not-a-tar")
            elif damage == "wrong_members":
                with tarfile.open(archive_path, "w:gz") as stream:
                    member = tarfile.TarInfo("wrong")
                    stream.addfile(member)
            else:
                archive_path.write_bytes(archive_path.read_bytes() + b"changed")
            if damage != "bad_digest":
                document = json.loads(manifest_path.read_text())
                document["sha256"] = archive.digest(archive_path)
                manifest_path.write_text(json.dumps(document))
        return result

    monkeypatch.setattr(Path, "rename", publish)
    with pytest.raises(archive.ProfileArchiveError):
        capture(source)
    assert (source[1] / "Default" / "proof").read_bytes() == b"opaque"
    # A rejected final snapshot is retained for diagnosis, never returned sealed.
    assert source[2].is_dir()


def test_capture_refuses_unreadable_manifest(source, monkeypatch):
    original = Path.read_text

    def unreadable(path, *args, **kwargs):
        if path.name == archive.MANIFEST_NAME:
            raise PermissionError(errno.EACCES, "private text", "private filename")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)
    with pytest.raises(
        archive.ProfileArchiveError, match="manifest_read_failed"
    ) as caught:
        capture(source)
    assert caught.value.details["error_class"] == "PermissionError"
    assert "private" not in caught.value.details["message"]
    assert not source[2].exists()


def test_capture_flushes_files_and_directories_before_success(source, monkeypatch):
    calls = []
    original = archive.sync_snapshot

    def sync(directory, names):
        calls.append((directory, names))
        original(directory, names)

    monkeypatch.setattr(archive, "sync_snapshot", sync)
    capture(source)
    assert calls[0][1] == (archive.ARCHIVE_NAME, archive.MANIFEST_NAME)
    assert calls[1] == (source[2].parent, ())


def test_capture_does_not_seal_when_file_flush_fails(source, monkeypatch):
    def failed(_):
        raise OSError(errno.EIO, "private")

    monkeypatch.setattr(validation.os, "fsync", failed)
    with pytest.raises(archive.ProfileArchiveError, match="capture_seal_failed"):
        capture(source)
    assert not source[2].exists()


@pytest.mark.parametrize("state", ["missing", "empty"])
def test_capture_refuses_missing_or_empty_source(source, monkeypatch, state):
    import shutil

    shutil.rmtree(source[1])
    if state == "empty":
        source[1].mkdir(mode=0o700)
    with pytest.raises(archive.ProfileArchiveError):
        capture(source)
    assert not source[2].exists()
