"""Tests for yoke_core.domain.lock_helper."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from yoke_core.domain import lock_helper


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


def _write_config(path: Path, **overrides: int) -> Path:
    lines = [f"{k}={v}" for k, v in overrides.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_read_lock_settings_uses_defaults_when_config_missing(tmp_path: Path) -> None:
    retries, sleep_seconds, stale_seconds = lock_helper._read_lock_settings(
        tmp_path / "missing-config"
    )
    assert retries == lock_helper.DEFAULT_RETRIES
    assert sleep_seconds == lock_helper.DEFAULT_SLEEP_MS / 1000.0
    assert stale_seconds == lock_helper.DEFAULT_STALE_SECONDS


def test_read_lock_settings_reads_overrides(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path / "config",
        lock_retries=3,
        lock_sleep_ms=10,
        lock_stale_seconds=5,
    )
    retries, sleep_seconds, stale_seconds = lock_helper._read_lock_settings(config)
    assert retries == 3
    assert sleep_seconds == pytest.approx(0.01)
    assert stale_seconds == 5


def test_read_lock_settings_ignores_comments_and_whitespace(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.write_text(
        "# a comment\n   lock_retries=7   # inline\nlock_sleep_ms=  \n",
        encoding="utf-8",
    )
    retries, sleep_seconds, _ = lock_helper._read_lock_settings(config)
    assert retries == 7
    # empty value should fall back to default
    assert sleep_seconds == lock_helper.DEFAULT_SLEEP_MS / 1000.0


# ---------------------------------------------------------------------------
# Acquire / release
# ---------------------------------------------------------------------------


def test_acquire_lock_creates_directory(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "config", lock_retries=1, lock_sleep_ms=1)
    lock_dir = tmp_path / "thing.lock"
    assert lock_helper.acquire_lock(lock_dir, config) is True
    assert lock_dir.is_dir()
    lock_helper.release_lock(lock_dir)
    assert not lock_dir.exists()


def test_acquire_lock_creates_missing_parent_directory(tmp_path: Path) -> None:
    # Regression: a first-ever board rebuild in a repo whose board directory
    # (e.g. .yoke/) does not exist yet must create the ancestor path rather
    # than raising FileNotFoundError from a parent-less mkdir().
    config = _write_config(tmp_path / "config", lock_retries=1, lock_sleep_ms=1)
    lock_dir = tmp_path / ".yoke" / "BOARD.md.lock"
    assert not lock_dir.parent.exists()
    assert lock_helper.acquire_lock(lock_dir, config) is True
    assert lock_dir.is_dir()
    lock_helper.release_lock(lock_dir)
    assert not lock_dir.exists()


def test_acquire_lock_fails_when_held(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path / "config",
        lock_retries=1,
        lock_sleep_ms=1,
        lock_stale_seconds=3600,
    )
    lock_dir = tmp_path / "busy.lock"
    lock_dir.mkdir()
    # Pretend the lock is fresh (stat mtime is "now").
    assert lock_helper.acquire_lock(lock_dir, config) is False
    # Leave the pre-existing lock in place so we didn't corrupt it.
    assert lock_dir.is_dir()


def test_acquire_lock_breaks_stale_lock(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path / "config",
        lock_retries=1,
        lock_sleep_ms=1,
        lock_stale_seconds=1,
    )
    lock_dir = tmp_path / "stale.lock"
    lock_dir.mkdir()
    # Force mtime to a time older than stale_seconds.
    old_time = time.time() - 3600
    os.utime(lock_dir, (old_time, old_time))
    assert lock_helper.acquire_lock(lock_dir, config) is True
    assert lock_dir.is_dir()
    lock_helper.release_lock(lock_dir)


def test_release_lock_handles_missing_dir(tmp_path: Path) -> None:
    # Must not raise when the lock was never created.
    lock_helper.release_lock(tmp_path / "never-there")


def test_release_lock_falls_back_to_rmtree_for_non_empty(tmp_path: Path) -> None:
    lock_dir = tmp_path / "nonempty.lock"
    lock_dir.mkdir()
    (lock_dir / "inner").write_text("x", encoding="utf-8")
    lock_helper.release_lock(lock_dir)
    assert not lock_dir.exists()


def test_acquire_and_release_round_trip_then_reacquire(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "config", lock_retries=1, lock_sleep_ms=1)
    lock_dir = tmp_path / "rtrip.lock"
    assert lock_helper.acquire_lock(lock_dir, config) is True
    lock_helper.release_lock(lock_dir)
    assert lock_helper.acquire_lock(lock_dir, config) is True
    lock_helper.release_lock(lock_dir)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_acquire_and_release(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "config", lock_retries=1, lock_sleep_ms=1)
    lock_dir = tmp_path / "cli.lock"
    rc = lock_helper.main(["acquire", str(lock_dir), "--config", str(config)])
    assert rc == 0
    assert lock_dir.is_dir()

    rc = lock_helper.main(["release", str(lock_dir)])
    assert rc == 0
    assert not lock_dir.exists()


def test_cli_acquire_reports_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _write_config(
        tmp_path / "config",
        lock_retries=1,
        lock_sleep_ms=1,
        lock_stale_seconds=3600,
    )
    lock_dir = tmp_path / "taken.lock"
    lock_dir.mkdir()
    rc = lock_helper.main(["acquire", str(lock_dir), "--config", str(config)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "Could not acquire lock" in err
    assert str(lock_dir) in err


def test_cli_autoresolves_config_from_yoke_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    yoke_root = tmp_path / "data"
    yoke_root.mkdir()
    _write_config(yoke_root / "config", lock_retries=1, lock_sleep_ms=1)
    monkeypatch.setenv("YOKE_ROOT", str(yoke_root))
    lock_dir = tmp_path / "env.lock"
    rc = lock_helper.main(["acquire", str(lock_dir)])
    assert rc == 0
    assert lock_dir.is_dir()
    lock_helper.release_lock(lock_dir)


def test_cli_autoresolves_config_from_repo_root_yoke_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    yoke_root = repo_root / "data"
    yoke_root.mkdir(parents=True)
    _write_config(yoke_root / "config", lock_retries=1, lock_sleep_ms=1)
    monkeypatch.setenv("YOKE_ROOT", str(repo_root))
    lock_dir = tmp_path / "repo-env.lock"
    rc = lock_helper.main(["acquire", str(lock_dir)])
    assert rc == 0
    assert lock_dir.is_dir()
    lock_helper.release_lock(lock_dir)
