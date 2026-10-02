"""Profile snapshots survive a clean-home reset without becoming home state."""

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile

import pytest

from yoke_harness import browser_profile_archive as snapshots


RELATIVE = ".yoke/secrets/capability-secrets/project/browser-control/profile"


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshots, "profile_writers_absent", lambda _: None)
    home = tmp_path / "home"
    profile = home / RELATIVE
    profile.mkdir(mode=0o700, parents=True)
    profile.parent.chmod(0o700)
    (profile / "Default").mkdir()
    (profile / "Default" / "Cookies").write_bytes(b"opaque-test-profile")
    (profile / "SingletonLock").symlink_to("host-99999")
    baseline = tmp_path / "goldens" / "profile"
    receipt = snapshots.capture(home, baseline, "project", RELATIVE)
    return home, profile, baseline, receipt


def test_separate_profile_survives_home_reset_and_restores_only_explicitly(snapshot):
    home, profile, baseline, receipt = snapshot
    assert receipt["sealed"] is True
    assert receipt["browser_profile_baseline_path"] == str(baseline)
    assert (baseline / snapshots.ARCHIVE_NAME).stat().st_mode & 0o077 == 0
    shutil.rmtree(home / ".yoke")
    assert not (home / ".yoke").exists()
    assert baseline.is_dir()
    with pytest.raises(snapshots.ProfileArchiveError, match="requires_installed_yoke"):
        snapshots.restore(home, baseline, "project", RELATIVE)
    assert not (home / ".yoke").exists()
    (home / ".yoke").mkdir(mode=0o700)
    snapshots.restore(home, baseline, "project", RELATIVE)
    assert (profile / "Default" / "Cookies").read_bytes() == b"opaque-test-profile"
    assert not (profile / "SingletonLock").is_symlink()
    assert (profile / "Default" / "Cookies").stat().st_mode & 0o077 == 0


def test_restore_refuses_overwriting_live_profile(snapshot):
    home, profile, baseline, _ = snapshot
    with pytest.raises(snapshots.ProfileArchiveError, match="destination_occupied"):
        snapshots.restore(home, baseline, "project", RELATIVE)
    assert (profile / "Default" / "Cookies").read_bytes() == b"opaque-test-profile"


@pytest.mark.parametrize("mismatch", ["project", "digest", "owner", "mode"])
def test_restore_rejects_mismatched_or_unsealed_snapshot_before_mutation(
    snapshot, mismatch
):
    home, profile, baseline, _ = snapshot
    shutil.rmtree(profile)
    manifest_path = baseline / snapshots.MANIFEST_NAME
    document = json.loads(manifest_path.read_text())
    if mismatch == "project":
        document["project"] = "another-project"
    elif mismatch == "digest":
        document["sha256"] = "0" * 64
    elif mismatch == "owner":
        document["uid"] = os.getuid() + 1
    else:
        baseline.chmod(0o755)
    manifest_path.write_text(json.dumps(document))
    with pytest.raises(snapshots.ProfileArchiveError):
        snapshots.restore(home, baseline, "project", RELATIVE)
    assert not profile.exists()


@pytest.mark.parametrize(
    "name,kind",
    [
        ("../escape", "file"),
        ("/escape", "file"),
        ("Default/link", "symlink"),
        ("Default/link", "hardlink"),
    ],
)
def test_restore_refuses_unsafe_archive_even_with_matching_digest(snapshot, name, kind):
    home, profile, baseline, _ = snapshot
    shutil.rmtree(profile)
    archive_path = baseline / snapshots.ARCHIVE_NAME
    with tarfile.open(archive_path, "w:gz") as archive:
        member = tarfile.TarInfo(name)
        if kind != "file":
            member.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
            member.linkname = "/outside"
            archive.addfile(member)
        else:
            member.size = 1
            archive.addfile(member, io.BytesIO(b"x"))
    manifest_path = baseline / snapshots.MANIFEST_NAME
    document = json.loads(manifest_path.read_text())
    document["sha256"] = snapshots.digest(archive_path)
    manifest_path.write_text(json.dumps(document))
    with pytest.raises(snapshots.ProfileArchiveError, match="archive_unsafe"):
        snapshots.restore(home, baseline, "project", RELATIVE)
    assert not profile.exists()


def test_capture_refuses_active_writer_and_keeps_profile(snapshot, monkeypatch):
    home, profile, baseline, _ = snapshot

    def busy(_):
        raise snapshots.ProfileArchiveError("browser_profile_writer_active")

    monkeypatch.setattr(snapshots, "profile_writers_absent", busy)
    destination = baseline.with_name("new-profile")
    with pytest.raises(snapshots.ProfileArchiveError, match="writer_active"):
        snapshots.capture(home, destination, "project", RELATIVE)
    assert not destination.exists()
    assert (profile / "Default" / "Cookies").is_file()


def test_capture_never_overwrites_snapshot(snapshot):
    home, _, baseline, _ = snapshot
    original = (baseline / snapshots.ARCHIVE_NAME).read_bytes()
    with pytest.raises(snapshots.ProfileArchiveError, match="destination_occupied"):
        snapshots.capture(home, baseline, "project", RELATIVE)
    assert (baseline / snapshots.ARCHIVE_NAME).read_bytes() == original


@pytest.mark.parametrize("writer", ["command", "descriptor", "unrelated"])
def test_privileged_inventory_checks_same_user_commands_and_descriptors(
    tmp_path, monkeypatch, capsys, writer
):
    monkeypatch.setattr(sys, "platform", "linux")
    proc = tmp_path / "proc"
    process = proc / "101"
    descriptors = process / "fd"
    descriptors.mkdir(parents=True)
    profile = tmp_path / "private-profile"
    command = str(profile) if writer == "command" else "systemd"
    (process / "cmdline").write_bytes(command.encode())
    target = profile / "opaque (deleted)" if writer == "descriptor" else tmp_path
    (descriptors / "3").symlink_to(target)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        sys, "argv", ["inventory", str(os.getuid()), str(profile), "102"]
    )
    program = snapshots.WRITER_INVENTORY_PROGRAM.replace(
        'Path("/proc")', f"Path({str(proc)!r})"
    )
    if writer == "unrelated":
        exec(compile(program, "writer-inventory", "exec"), {})
        assert json.loads(capsys.readouterr().out) == {"ok": True}
    else:
        with pytest.raises(SystemExit) as stopped:
            exec(compile(program, "writer-inventory", "exec"), {})
        assert stopped.value.code == 64
        assert json.loads(capsys.readouterr().out) == {
            "ok": False,
            "reason": "browser_profile_writer_active",
        }


def test_archive_uses_noninteractive_read_only_privileged_inventory(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    profile = snapshots.Path("/home/testuser/private-profile")

    def inventory(argv, **options):
        assert argv[:4] == ["sudo", "-n", "/usr/bin/python3", "-c"]
        assert argv[4] == snapshots.WRITER_INVENTORY_PROGRAM
        assert argv[5:] == [str(os.getuid()), str(profile), str(os.getpid())]
        assert options == {
            "capture_output": True,
            "text": True,
            "timeout": 30,
            "check": False,
        }
        return subprocess.CompletedProcess(argv, 0, '{"ok":true}', "")

    monkeypatch.setattr(subprocess, "run", inventory)
    snapshots.profile_writers_absent(profile)


@pytest.mark.parametrize(
    "stdout,code,reason",
    [
        (
            '{"ok":false,"reason":"browser_profile_writer_active"}',
            64,
            "browser_profile_writer_active",
        ),
        ('{"ok":true}', 1, "browser_profile_writer_inventory_unavailable"),
        ("not-json", 1, "browser_profile_writer_inventory_unavailable"),
        ("[]", 0, "browser_profile_writer_inventory_unavailable"),
    ],
)
def test_inventory_failure_refuses_without_masking_writer_reason(
    monkeypatch, stdout, code, reason
):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **_: subprocess.CompletedProcess(
            argv, code, stdout, "private diagnostic"
        ),
    )
    with pytest.raises(snapshots.ProfileArchiveError, match=reason):
        snapshots.profile_writers_absent(
            snapshots.Path("/home/testuser/private-profile")
        )


def test_inventory_timeout_refuses_without_mutating_profile(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    def timeout(*_, **__):
        raise subprocess.TimeoutExpired("metadata-inventory", 30)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(
        snapshots.ProfileArchiveError, match="writer_inventory_unavailable"
    ):
        snapshots.profile_writers_absent(
            snapshots.Path("/home/testuser/private-profile")
        )


@pytest.mark.parametrize("runtime_os", ["linux", "darwin"])
def test_profile_capture_and_restore_bind_runtime_os(tmp_path, monkeypatch, runtime_os):
    monkeypatch.setattr(sys, "platform", runtime_os)
    monkeypatch.setattr(snapshots, "profile_writers_absent", lambda _: None)
    home = tmp_path / "home"
    profile = home / RELATIVE
    profile.mkdir(mode=0o700, parents=True)
    profile.parent.chmod(0o700)
    (profile / "proof").write_bytes(b"opaque")
    baseline = tmp_path / "goldens" / "profile"
    snapshots.capture(home, baseline, "project", RELATIVE)
    manifest = json.loads((baseline / snapshots.MANIFEST_NAME).read_text())
    assert manifest["os"] == ("macos" if runtime_os == "darwin" else "linux")
    shutil.rmtree(profile)
    assert snapshots.restore(home, baseline, "project", RELATIVE)["restored"]
    assert (profile / "proof").read_bytes() == b"opaque"
