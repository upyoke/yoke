"""Restore refuses damaged snapshots with useful, content-free diagnostics."""

import errno
import json
import shutil
import tarfile
from pathlib import Path

import pytest

from yoke_harness import browser_profile_archive as archive
from yoke_harness.browser_profile_archive_validation import archive_step

RELATIVE = ".yoke/secrets/capability-secrets/project/browser-control/profile"
SECRET = "private-profile-content-that-must-not-leave-the-host"


@pytest.fixture
def sealed(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "profile_writers_absent", lambda _: None)
    home = tmp_path / "home"
    profile = home / RELATIVE
    profile.mkdir(mode=0o700, parents=True)
    profile.parent.chmod(0o700)
    (profile / "proof").write_text(SECRET)
    baseline = tmp_path / "goldens" / "profile"
    archive.capture(home, baseline, "project", RELATIVE)
    shutil.rmtree(profile)
    return home, profile, baseline


def restore(sealed):
    home, _, baseline = sealed
    return archive.restore(home, baseline, "project", RELATIVE)


def refusal(sealed, step, error_class):
    with pytest.raises(archive.ProfileArchiveError) as caught:
        restore(sealed)
    error = caught.value
    assert str(error) == f"browser_profile_{step}_failed"
    assert error.details["step"] == step
    assert error.details["error_class"] == error_class
    assert error.details["message"]
    assert error.details["recovery"]
    assert SECRET not in json.dumps(error.details)
    assert not sealed[1].exists()
    return error.details


def test_valid_capture_still_restores(sealed):
    assert restore(sealed)["restored"] is True
    assert (sealed[1] / "proof").read_text() == SECRET


def test_manifest_parse_failure_is_specific_and_does_not_echo_document(sealed):
    (sealed[2] / archive.MANIFEST_NAME).write_text(SECRET)
    details = refusal(sealed, "manifest_parse", "JSONDecodeError")
    assert details["message"] == "Invalid manifest JSON at line 1, column 1"


def test_manifest_encoding_failure_never_echoes_input_bytes(sealed):
    (sealed[2] / archive.MANIFEST_NAME).write_bytes(b"\xff" + SECRET.encode())
    assert (
        refusal(sealed, "manifest_read", "UnicodeDecodeError")["message"]
        == "Manifest is not valid UTF-8"
    )


def test_manifest_read_error_omits_filename_and_custom_error_text(sealed, monkeypatch):
    original = Path.read_text

    def read(path, *args, **kwargs):
        if path.name == archive.MANIFEST_NAME:
            raise OSError(errno.EIO, SECRET, SECRET)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    details = refusal(sealed, "manifest_read", "OSError")
    assert details["message"] == "Input/output error"


def test_validation_permission_error_is_specific(sealed, monkeypatch):
    def unreadable(*_, **__):
        raise PermissionError(errno.EACCES, SECRET, SECRET)

    monkeypatch.setattr(archive, "private_owned", unreadable)
    assert (
        refusal(sealed, "permission", "PermissionError")["message"]
        == "Permission denied"
    )


def test_archive_digest_read_error_is_specific(sealed, monkeypatch):
    def unreadable(*_):
        raise OSError(errno.EIO, SECRET, SECRET)

    monkeypatch.setattr(archive, "digest", unreadable)
    refusal(sealed, "archive_read", "OSError")


def test_invalid_archive_open_is_specific_and_keeps_seal(sealed):
    baseline = sealed[2]
    archive_path = baseline / archive.ARCHIVE_NAME
    archive_path.write_bytes(SECRET.encode())
    manifest = baseline / archive.MANIFEST_NAME
    document = json.loads(manifest.read_text())
    document["sha256"] = archive.digest(archive_path)
    manifest.write_text(json.dumps(document))
    refusal(sealed, "archive_open", "ReadError")
    assert archive_path.read_bytes() == SECRET.encode()


def test_archive_member_read_failure_is_specific(sealed, monkeypatch):
    def broken(*_):
        raise tarfile.ReadError(SECRET)

    monkeypatch.setattr(archive, "archive_members", broken)
    refusal(sealed, "archive_read", "ReadError")


@pytest.mark.parametrize(
    "error",
    [
        OSError(errno.ENOSPC, SECRET, SECRET),
        tarfile.ReadError(SECRET),
        EOFError(SECRET),
        ValueError(SECRET),
    ],
)
def test_extraction_failure_cleans_temporary_copy_and_preserves_seal(
    sealed, monkeypatch, error
):
    checksum = archive.digest(sealed[2] / archive.ARCHIVE_NAME)

    def broken(*_):
        raise error

    monkeypatch.setattr(archive.shutil, "copyfileobj", broken)
    refusal(sealed, "extraction", type(error).__name__)
    assert not list(sealed[1].parent.glob(".browser-profile-*"))
    assert archive.digest(sealed[2] / archive.ARCHIVE_NAME) == checksum


def test_named_security_refusal_is_preserved_by_step_wrapper():
    with pytest.raises(
        archive.ProfileArchiveError, match="browser_profile_foreign_owner"
    ) as caught:
        with archive_step("permission"):
            archive.require(False, "browser_profile_foreign_owner")
    assert caught.value.details == {}
