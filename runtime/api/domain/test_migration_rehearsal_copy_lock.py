"""Real process admission, endpoint aliases and orphaned transfer lifetimes."""

from __future__ import annotations

import multiprocessing
import os
import signal
import sys
import time

import pytest

from yoke_core.domain import migration_rehearsal_copy_lock as admission
from yoke_core.domain import migration_fleet_preflight_transfer as transfer
from yoke_core.domain.postgres_cluster import ClusterSpec


def _hold(spec, home, entered, release):
    admission.machine_config.yoke_home = lambda: home
    with admission.copy_lock(spec, "copy"):
        entered.set()
        assert release.wait(10)


def test_separate_drivers_refuse_then_reuse_and_keep_stable_inode(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    monkeypatch.setattr(admission.machine_config, "yoke_home", lambda: home)
    spec = ClusterSpec(tmp_path / "cluster", "test")
    spec.sock_dir.mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(spec.sock_dir, target_is_directory=True)
    same = ClusterSpec(tmp_path / "different-root", "other-role", socket_dir=alias)
    ctx = multiprocessing.get_context("spawn")
    entered, release = ctx.Event(), ctx.Event()
    process = ctx.Process(target=_hold, args=(spec, home, entered, release))
    process.start()
    try:
        assert entered.wait(10)
        path = admission.lock_path(spec, "copy")
        inode = path.stat().st_ino
        path.write_text('{"pid":999999999,"started_at":0}')
        with pytest.raises(
            admission.RehearsalCopyBusy, match="rehearsal_copy_busy.*retry"
        ):
            with admission.copy_lock(same, "copy"):
                pytest.fail("same endpoint admitted twice")
        with admission.copy_lock(spec, "other-copy"):
            pass
        with admission.copy_lock(
            ClusterSpec(tmp_path / "other-cluster", "test"), "copy"
        ):
            pass
        release.set()
        process.join(10)
        assert process.exitcode == 0
        with admission.copy_lock(same, "copy"):
            assert path.stat().st_ino == inode
    finally:
        release.set()
        process.join(10)
        if process.is_alive():
            process.kill()
            process.join()


def test_actual_postgres_identifier_truncation_coordinates(tmp_path, monkeypatch):
    monkeypatch.setattr(admission.machine_config, "yoke_home", lambda: tmp_path)
    spec = ClusterSpec(tmp_path / "cluster", "test")
    assert admission.lock_path(spec, "x" * 63 + "a") == admission.lock_path(
        spec, "x" * 63 + "b"
    )
    assert admission.lock_path(spec, "é" * 32 + "a") == admission.lock_path(
        spec, "é" * 32 + "b"
    )


def test_malformed_diagnostics_cannot_change_busy_admission(tmp_path, monkeypatch):
    monkeypatch.setattr(admission.machine_config, "yoke_home", lambda: tmp_path)
    spec = ClusterSpec(tmp_path / "cluster", "test")
    with admission.copy_lock(spec, "copy"):
        admission.lock_path(spec, "copy").write_text('{"pid":1e999,"started_at":0}')
        with pytest.raises(
            admission.RehearsalCopyBusy, match="diagnostics unavailable.*retry"
        ):
            with admission.copy_lock(spec, "copy"):
                pytest.fail("diagnostic metadata admitted a competing copy")


def _transfer_parent(spec, home, ready, release, finished, runner):
    admission.machine_config.yoke_home = lambda: home
    script = (
        "import os, pathlib, sys, time; "
        "ready, release, finished = map(pathlib.Path, sys.argv[1:]); "
        "ready.write_text(str(os.getpid())); "
        "exec('while not release.exists():\\n time.sleep(0.01)'); "
        "finished.write_text('stopped')"
    )
    with admission.copy_lock(spec, "copy"):
        if runner == "declared":
            from yoke_core.domain.migration_fleet_declared_plan import run_declared

            run_declared(
                [sys.executable, "-c", script, str(ready), str(release), str(finished)],
                cwd=home,
                env_var="FIXTURE_DSN",
                dsn="dbname=fixture",
            )
            return
        transfer.run_transfer(
            [sys.executable, "-c", script, str(ready), str(release), str(finished)],
            timeout=10,
            progress_file=ready if runner == "dump" else None,
        )


def _until(predicate):
    deadline = time.monotonic() + 10
    while not predicate():
        assert time.monotonic() < deadline, "fixture synchronization timed out"
        time.sleep(0.01)


@pytest.mark.parametrize("runner", ["restore", "dump", "declared"])
def test_killed_parent_does_not_release_a_live_transfer(tmp_path, monkeypatch, runner):
    home = tmp_path / "home"
    monkeypatch.setattr(admission.machine_config, "yoke_home", lambda: home)
    spec = ClusterSpec(tmp_path / "cluster", "test")
    ready, release, finished = [
        tmp_path / name for name in ("ready", "release", "finished")
    ]
    ctx = multiprocessing.get_context("spawn")
    parent = ctx.Process(
        target=_transfer_parent, args=(spec, home, ready, release, finished, runner)
    )
    parent.start()
    try:
        _until(ready.exists)
        parent.kill()
        parent.join(10)
        with pytest.raises(admission.RehearsalCopyBusy):
            with admission.copy_lock(spec, "copy"):
                pytest.fail("live orphaned transfer lost admission")
        release.touch()
        _until(finished.exists)

        def reusable():
            try:
                with admission.copy_lock(spec, "copy"):
                    return True
            except admission.RehearsalCopyBusy:
                return False

        _until(reusable)
    finally:
        release.touch()
        if parent.is_alive():
            parent.kill()
        parent.join(10)
        if ready.exists() and not finished.exists():
            os.kill(int(ready.read_text()), signal.SIGKILL)


def test_interruption_reaps_child_before_releasing_admission(tmp_path, monkeypatch):
    monkeypatch.setattr(
        admission.machine_config, "yoke_home", lambda: tmp_path / "home"
    )
    spec = ClusterSpec(tmp_path / "cluster", "test")
    real_popen = admission.subprocess.Popen
    children = []

    class InterruptingProcess:
        def __init__(self, *args, **kwargs):
            self.process = real_popen(*args, **kwargs)
            children.append(self.process)
            self.calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.process.__exit__(*args)

        def communicate(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise KeyboardInterrupt
            return self.process.communicate(**kwargs)

        def __getattr__(self, name):
            return getattr(self.process, name)

    monkeypatch.setattr(admission.subprocess, "Popen", InterruptingProcess)
    with admission.copy_lock(spec, "copy"):
        with pytest.raises(KeyboardInterrupt):
            transfer.run_transfer(
                [sys.executable, "-c", "import time; time.sleep(10)"], timeout=10
            )
        assert children[0].returncode is not None
        with pytest.raises(admission.RehearsalCopyBusy):
            with admission.copy_lock(spec, "copy"):
                pass
    with admission.copy_lock(spec, "copy"):
        pass
