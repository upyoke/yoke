"""Ownership binding between a watcher run and its capture pair.

Covers the producer half — resolving the pair and stamping the pid
marker as the progress capture's first line — plus the reader helpers
``watch_tail`` uses to tell a live writer from a capture nobody writes,
and the refusals that name the cause and the recovery step.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pytest

from yoke_core.tools import _watch_capture_binding as binding


def _namespace(raw: Path | None, progress: Path | None) -> argparse.Namespace:
    return argparse.Namespace(raw_capture=raw, progress_capture=progress)


def test_binding_stamps_the_running_process_as_the_capture_owner(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw.log"
    progress = tmp_path / "progress.log"

    bound_raw, bound_progress = binding.bind_capture_paths(
        _namespace(raw, progress), "pytest"
    )

    assert (bound_raw, bound_progress) == (raw, progress)
    first_line = progress.read_text(encoding="utf-8").splitlines()[0]
    assert binding.writer_pid(first_line + "\n") == os.getpid()


def test_binding_mints_a_pair_when_either_capture_flag_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    minted_raw = tmp_path / "minted-raw.log"
    minted_progress = tmp_path / "minted-progress.log"
    monkeypatch.setattr(
        binding, "mint_capture_paths", lambda kind: (minted_raw, minted_progress)
    )
    explicit_raw = tmp_path / "explicit-raw.log"

    bound_raw, bound_progress = binding.bind_capture_paths(
        _namespace(explicit_raw, None), "merge"
    )

    # The operator carve-out survives: an explicit raw path is kept and
    # only the missing half is minted.
    assert bound_raw == explicit_raw
    assert bound_progress == minted_progress
    assert binding.writer_pid(minted_progress.read_text(encoding="utf-8"))


def test_binding_truncates_a_reused_progress_capture(tmp_path: Path) -> None:
    """A re-run must not leave a previous run's lines above its marker."""
    progress = tmp_path / "progress.log"
    progress.write_text("stale line from an earlier run\n", encoding="utf-8")

    binding.bind_capture_paths(_namespace(tmp_path / "raw.log", progress), "doctor")

    assert progress.read_text(encoding="utf-8").splitlines() == [
        binding.writer_marker_line("doctor").rstrip("\n")
    ]


def test_writer_pid_reads_only_the_marker_line() -> None:
    assert binding.writer_pid("# watch_pytest writer_pid=4242\n") == 4242
    assert binding.writer_pid("# watch_pytest raw=/tmp/raw.log\n") is None
    assert binding.writer_pid("[ 42%] some progress\n") is None


def test_writer_alive_reports_this_process_and_not_an_unused_pid() -> None:
    assert binding.writer_alive(os.getpid()) is True
    # PID 0 is the process group of the caller on POSIX; a very high pid
    # that no process holds is the portable "gone" case.
    gone = 2**31 - 1
    assert binding.writer_alive(gone) is False


def test_refusals_name_the_cause_and_the_recovery_step(tmp_path: Path) -> None:
    capture = tmp_path / "progress.log"

    unwritten = binding.unwritten_capture_refusal(capture, grace_seconds=30.0)
    assert str(capture) in unwritten
    assert "--raw-capture/--progress-capture" in unwritten
    assert "--print-streaming-pair" in unwritten

    dead = binding.dead_writer_refusal(capture, pid=4242)
    assert "4242" in dead
    assert "exit sentinel" in dead
    assert "--print-streaming-pair" in dead
