"""Registered goldens stay; older snapshots go, and a full disk refuses."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from yoke_harness.golden_snapshot_retention import (
    SnapshotRetentionError,
    apply_retention,
    removable_snapshot_names,
    removal_order,
    retain_after_verified_capture,
)
from yoke_harness.ssh_linux_baseline import ABSENT_HOME_PATHS, _ARCHIVE_PROGRAM
from yoke_harness.ssh_mac_golden_capture_contract import (
    CAPTURE_REFUSAL_KIND_INSUFFICIENT_SPACE,
    capture_refusal_recovery,
)


def _run(command: str, *, timeout: int = 60, input_text: str | None = None):
    return subprocess.run(
        ["/bin/sh", "-c", command],
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input_text,
    )


def test_prune_leaves_only_the_registered_golden_on_a_user_root(tmp_path):
    parent = tmp_path / "yoketest"
    parent.mkdir()
    for name in (
        "yoketest-home-20261001",
        "home-20261002",
        "mixed-snapshot",
        "browser-profile",
        ".yoke-golden-unregistered",
    ):
        (parent / name).mkdir()
    (parent / "yoketest-home-20261001.probes").write_text("old")
    registered = parent / "yoketest-home-20261014"
    registered.mkdir()
    (registered / "home.tar.gz").write_bytes(b"golden")
    (parent / "yoketest-home-20261014.probes").write_text("probes")
    (parent / "yoketest-home-20261014.manifest").write_text("manifest")

    removed = apply_retention(
        _run,
        destination=str(registered),
        user="yoketest",
        kept_paths=[str(registered)],
    )

    assert set(removed) == {
        "yoketest-home-20261001",
        "yoketest-home-20261001.probes",
        "home-20261002",
        "mixed-snapshot",
        "browser-profile",
        ".yoke-golden-unregistered",
    }
    assert set(os.listdir(parent)) == {
        "yoketest-home-20261014",
        "yoketest-home-20261014.probes",
        "yoketest-home-20261014.manifest",
    }


def test_a_shared_parent_keeps_another_users_golden():
    names = removable_snapshot_names(
        (
            "yoketest-home-20261001",
            "yoketest-home-20261014",
            "yoketest-home-20261014.probes",
            "yoketest-home-20261014.manifest",
            "other-home-20261005",
            "home-20261002",
            ".yoke-golden-temp",
            "notes",
        ),
        registered_names=["yoketest-home-20261014"],
        user="yoketest",
        parent_name="yoke-golden",
    )
    assert set(names) == {
        "yoketest-home-20261001",
        "home-20261002",
        ".yoke-golden-temp",
    }


def test_a_shared_machine_keeps_every_projects_registered_golden(tmp_path):
    # Two projects register one machine and share its golden parent. A
    # capture for one project prunes only snapshots no project registered.
    parent = tmp_path / "yoke-golden"
    parent.mkdir()
    other_project = parent / "testy-home-20261013T1847Z"
    superseded = parent / "testy-home-20261001"
    registered = parent / "testy-home-20261014T1230Z"
    for snapshot in (other_project, superseded, registered):
        snapshot.mkdir()
        for suffix in (".probes", ".manifest"):
            (parent / (snapshot.name + suffix)).write_text(suffix)

    removed = apply_retention(
        _run,
        destination=str(registered),
        user="testy",
        kept_paths=[str(other_project), str(registered), "/elsewhere/testy-home-x"],
    )

    assert set(removed) == {
        "testy-home-20261001",
        "testy-home-20261001.probes",
        "testy-home-20261001.manifest",
    }
    assert set(os.listdir(parent)) == {
        name + suffix
        for name in (other_project.name, registered.name)
        for suffix in ("", ".probes", ".manifest")
    }


def _seal(path):
    # Capture seals a golden read-only; macOS also keeps deny-delete ACLs.
    if sys.platform == "darwin":
        subprocess.run(
            ["chmod", "-R", "+a", "everyone deny delete", str(path)], check=True
        )
    for root, dirs, files in os.walk(path, topdown=False):
        for name in files:
            os.chmod(os.path.join(root, name), 0o444)
        for name in dirs:
            os.chmod(os.path.join(root, name), 0o555)
    os.chmod(path, 0o555 if path.is_dir() else 0o444)


def test_a_sealed_retired_golden_is_removed(tmp_path):
    parent = tmp_path / "yoke-golden"
    parent.mkdir()
    sealed = parent / "testy-home-20261010T0424Z"
    (sealed / "Library" / "Preferences").mkdir(parents=True)
    (sealed / "Library" / "Preferences" / "plist").write_text("old")
    (sealed / ".zshrc").write_text("old")
    probes = parent / "testy-home-20261010T0424Z.probes"
    probes.write_text("old")
    registered = parent / "testy-home-20261019T0039Z"
    registered.mkdir()
    _seal(sealed)
    _seal(probes)

    removed = apply_retention(
        _run,
        destination=str(registered),
        user="testy",
        kept_paths=[str(registered)],
    )

    assert set(removed) == {sealed.name, probes.name}
    assert os.listdir(parent) == [registered.name]


def test_a_failed_removal_names_the_remote_error_not_its_output():
    listing = "/g/testy/old\0/g/testy/current\0"

    def run(command, *, timeout=60):
        if command.startswith("find "):
            return subprocess.CompletedProcess(command, 0, stdout=listing, stderr="")
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="progress",
            stderr="rm: /g/testy/old: Operation\nnot permitted",
        )

    with pytest.raises(SnapshotRetentionError) as raised:
        apply_retention(
            run, destination="/g/testy/current", user="testy", kept_paths=[]
        )

    assert "rm: /g/testy/old: Operation not permitted" in raised.value.detail
    assert "progress" not in raised.value.detail


def _verified(**fields):
    return {
        "status": "verified",
        "golden_baseline_path": "/Users/Shared/yoke-golden/testy-home-new",
        **fields,
    }


def test_a_server_without_kept_goldens_keeps_every_snapshot():
    # An older server cannot name other projects' goldens, so nothing is
    # deleted and the refusal says why and how to clean up by hand.
    with pytest.raises(SnapshotRetentionError) as raised:
        retain_after_verified_capture("golden_capture", True, _verified(), {})

    assert raised.value.code == "golden_snapshot_retention_failed"
    assert "kept_golden_paths" in raised.value.detail
    assert "another project registered" in raised.value.recovery
    assert "yoke test-machine get" in raised.value.recovery


def test_an_unknown_registration_keeps_every_snapshot():
    with pytest.raises(SnapshotRetentionError) as raised:
        retain_after_verified_capture(
            "golden_capture",
            True,
            _verified(kept_golden_paths_unknown="project 3 is unreadable"),
            {},
        )

    assert "project 3 is unreadable" in raised.value.detail


def test_a_symlink_blocks_removal_and_leaves_the_target(tmp_path):
    parent = tmp_path / "yoketest"
    parent.mkdir()
    (parent / "old").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "kept").write_text("safe")
    (parent / "linked").symlink_to(outside)
    registered = parent / "current"
    registered.mkdir()

    with pytest.raises(SnapshotRetentionError) as raised:
        apply_retention(
            _run,
            destination=str(registered),
            user="yoketest",
            kept_paths=[str(registered)],
        )

    assert raised.value.code == "golden_snapshot_retention_failed"
    assert "symlink" in raised.value.detail
    assert str(registered) in raised.value.recovery
    assert not (parent / "old").exists()
    assert (outside / "kept").read_text() == "safe"


def test_a_failed_removal_keeps_that_name_and_removes_the_rest(tmp_path):
    parent = tmp_path / "yoketest"
    parent.mkdir()
    for name in ("home-1", "home-2-broken", "home-3"):
        (parent / name).mkdir()
        (parent / (name + ".manifest")).write_text("m")
    registered = parent / "current"
    registered.mkdir()

    def run_with_one_failing_rm(command, **kwargs):
        # The host refuses one folder, as a deny-delete ACL or busy mount would.
        failing_rm = (
            'rm() { case "$*" in *broken) echo "rm: denied" >&2; return 1 ;; '
            'esac; command rm "$@"; }\n'
        )
        return _run(failing_rm + command, **kwargs)

    with pytest.raises(SnapshotRetentionError) as raised:
        apply_retention(
            run_with_one_failing_rm,
            destination=str(registered),
            user="yoketest",
            kept_paths=[str(registered)],
        )

    assert set(os.listdir(parent)) == {"current", "home-2-broken"}
    detail = raised.value.detail
    assert "Kept: home-2-broken (failed)." in detail
    removed = detail.split("Removed: ", 1)[1].split(". Kept:", 1)[0].split(", ")
    assert set(removed[:3]) == {
        "home-1.manifest",
        "home-2-broken.manifest",
        "home-3.manifest",
    }
    assert set(removed[3:]) == {"home-1", "home-3"}
    assert "rm: denied" in detail


def test_sidecars_are_removed_before_their_folders():
    assert removal_order(
        ("home-1", "home-1.probes", "home-2", "home-2.manifest", "home-1.harness-clis")
    ) == (
        "home-1.probes",
        "home-2.manifest",
        "home-1.harness-clis",
        "home-1",
        "home-2",
    )


def test_low_disk_refuses_with_the_named_reason(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "blob").write_text("x" * 64)
    golden = tmp_path / "golden"
    program = _ARCHIVE_PROGRAM.replace(
        "shutil.disk_usage(baseline.parent).free",
        "0",
    )
    monkeypatch.chdir(home)
    result = subprocess.run(
        [sys.executable, "-c", program, "capture", str(home), str(golden)],
        input=json.dumps(ABSENT_HOME_PATHS),
        text=True,
        capture_output=True,
        env={**os.environ, "HOME": str(home)},
        check=False,
    )
    assert result.returncode != 0
    receipt = json.loads(result.stdout)
    assert receipt["reason"] == "golden_capture_insufficient_space"
    assert receipt["expected_bytes"] >= 64
    assert "yoke test-machine golden-capture" in receipt["recovery"]
    assert not golden.exists()


def test_mac_low_disk_recovery_names_the_cleanup():
    recovery = capture_refusal_recovery(
        CAPTURE_REFUSAL_KIND_INSUFFICIENT_SPACE,
        "/var/lib/yoke-golden/yoketest",
    )
    assert "yoke test-machine golden-capture" in recovery
    assert "/var/lib/yoke-golden/yoketest" in recovery
    assert ".probes" in recovery
