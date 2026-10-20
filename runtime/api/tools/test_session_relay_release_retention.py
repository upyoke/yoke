"""Automatic relay retention preserves rollback and running release packages."""

from __future__ import annotations

import json
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import sysconfig

import pytest

from runtime.api.tools.session_relay_release_test_support import (
    NEXT_RELEASE,
    RELEASE,
    fake_venv,
    relay_instance,
    runner_for,
)
from yoke_core.tools import session_relay_release_retention as retention
from yoke_core.tools.session_relay_release import RelayReleaseError
from yoke_core.tools.session_relay_release_install import pin_relay_release


THIRD_RELEASE = "0.2.0.202610140943"


def install(instance, version):
    pin_relay_release(
        instance=instance,
        served_build=version,
        create_venv=fake_venv,
        runner=runner_for(version, []),
    )
    return (instance.state_dir / "release").resolve()


def test_third_install_keeps_exactly_current_and_previous(tmp_path):
    instance = relay_instance(tmp_path)
    oldest = install(instance, RELEASE)
    previous = install(instance, NEXT_RELEASE)
    current = install(instance, THIRD_RELEASE)

    assert set((instance.state_dir / "releases").iterdir()) == {previous, current}
    assert not oldest.exists()
    receipt = json.loads((current / ".yoke-relay-release.json").read_text())
    assert receipt["previous_release"] == str(previous)


def test_failed_candidate_does_not_prune_any_release(tmp_path):
    instance = relay_instance(tmp_path)
    oldest = install(instance, RELEASE)
    current = install(instance, NEXT_RELEASE)
    orphan = instance.state_dir / "releases" / "old-unused"
    orphan.mkdir()

    with pytest.raises(RelayReleaseError):
        pin_relay_release(
            instance=instance,
            served_build=THIRD_RELEASE,
            create_venv=lambda _: (_ for _ in ()).throw(OSError("disk full")),
        )

    assert set((instance.state_dir / "releases").iterdir()) == {oldest, current, orphan}
    assert (instance.state_dir / "release").resolve() == current


def test_running_release_stays_until_a_later_install(tmp_path):
    instance = relay_instance(tmp_path)
    oldest = install(instance, RELEASE)
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import pathlib, sys; print('ready', flush=True); sys.stdin.read(); "
            "(pathlib.Path(sys.argv[1]) / '.yoke-relay-release.json').read_text()",
            str(oldest),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "ready"
        previous = install(instance, NEXT_RELEASE)
        current = install(instance, THIRD_RELEASE)
        assert set((instance.state_dir / "releases").iterdir()) == {
            oldest,
            previous,
            current,
        }
    finally:
        process.communicate(timeout=5)
    assert process.returncode == 0
    # Reusing the installed pin retries cleanup without rotating rollback.
    install(instance, THIRD_RELEASE)
    assert set((instance.state_dir / "releases").iterdir()) == {previous, current}


def test_directory_lease_preserves_packages_without_release_in_command(tmp_path):
    instance = relay_instance(tmp_path)
    oldest = install(instance, RELEASE)
    # Pass the root on stdin so ps cannot identify it; the directory lease must.
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import fcntl, os, sys; fd=os.open(sys.stdin.readline().strip(), os.O_RDONLY); "
            "fcntl.flock(fd, fcntl.LOCK_SH); print('ready', flush=True); sys.stdin.read()",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        process.stdin.write(str(oldest) + "\n")
        process.stdin.flush()
        assert process.stdout.readline().strip() == "ready"
        install(instance, NEXT_RELEASE)
        install(instance, THIRD_RELEASE)
        assert oldest.is_dir()
    finally:
        process.communicate(timeout=5)


def test_process_snapshot_failure_records_cleanup_recovery(tmp_path, monkeypatch):
    instance = relay_instance(tmp_path)
    oldest = install(instance, RELEASE)
    install(instance, NEXT_RELEASE)

    def unavailable(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, "", "unavailable")

    with monkeypatch.context() as scoped:
        scoped.setattr(retention.subprocess, "run", unavailable)
        with pytest.raises(RelayReleaseError, match="relay_release_prune_failed"):
            install(instance, THIRD_RELEASE)
    assert oldest.exists()
    failure = json.loads((instance.state_dir / "release-pin-error.json").read_text())
    assert "Recovery:" in failure["message"]
    assert "relay install" in failure["message"]
    install(instance, THIRD_RELEASE)
    assert not oldest.exists()
    assert not (instance.state_dir / "release-pin-error.json").exists()


def test_symlink_in_releases_never_removes_its_target(tmp_path):
    instance = relay_instance(tmp_path)
    install(instance, RELEASE)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").touch()
    link = instance.state_dir / "releases" / "not-owned"
    link.symlink_to(outside, target_is_directory=True)
    install(instance, NEXT_RELEASE)
    install(instance, THIRD_RELEASE)
    assert (outside / "keep").exists()
    assert link.is_symlink()


def test_installed_launcher_holds_selected_release_until_exit(tmp_path):
    instance = relay_instance(tmp_path)
    oldest = install(instance, RELEASE)
    relative = (
        Path(sysconfig.get_path("purelib"))
        .resolve()
        .relative_to(Path(sys.prefix).resolve())
    )
    package = oldest / relative / "yoke_cli"
    package.mkdir(parents=True)
    (package / "__init__.py").touch()
    (package / "main.py").write_text(
        "import sys\ndef main(argv):\n"
        "    print('ready', flush=True)\n"
        "    sys.stdin.read()\n"
        "    return 0\n"
    )
    process = subprocess.Popen(
        [sys.executable, str(instance.state_dir / "runtime" / "bin" / "yoke")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    descriptor = os.open(oldest, os.O_RDONLY)
    try:
        assert process.stdout.readline().strip() == "ready"
        with pytest.raises(BlockingIOError):
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        install(instance, NEXT_RELEASE)
        install(instance, THIRD_RELEASE)
        assert oldest.is_dir()
    finally:
        process.communicate(timeout=5)
        os.close(descriptor)
    install(instance, THIRD_RELEASE)
    assert not oldest.exists()
