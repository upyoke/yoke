"""A watched child's last words survive the moment it exits.

The reason this file exists: a run's terminal burst — its verdict, its
summary, its failure reason — is written immediately before the process
dies. If the reader treats "the child has exited" as "there is nothing
left to read", that burst is discarded and a finished run becomes an exit
code with no account of itself. On a failure that is the whole diagnosis.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from yoke_core.tools import watch_child_drain, watch_progress_stall
from yoke_core.tools._watch_digest import ProgressDigest
from yoke_core.tools._watch_throttle import (
    Classification,
    LineClass,
    ProgressGate,
    ThrottlePolicy,
)
from yoke_core.tools.watch_child_drain import drain_watched_child

#: The child stays quiet long enough that the reader waits on a timeout
#: rather than on data — the state a polling gate spends most of its life
#: in — and only then writes its outcome and exits. The silence matters:
#: the loss happens on a pass where the select found nothing, so a child
#: that speaks first would be read through the ordinary path instead.
_QUIET_THEN_OUTCOME = (
    "import sys, time\n"
    "time.sleep(0.2)\n"
    "sys.stdout.write('SUMMARY verdict=pass\\n')\n"
    "sys.stdout.write('{\"verdict\": \"pass\"}\\n')\n"
    "sys.stdout.flush()\n"
)


def _classify(line: str) -> Classification:
    if line.startswith("SUMMARY") or line.startswith("{"):
        return Classification(LineClass.SUMMARY)
    return Classification(LineClass.URGENT)


def _spawn(program: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", program],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        text=True,
    )


def test_shared_liveness_notice_defaults_to_five_minutes(monkeypatch) -> None:
    monkeypatch.delenv(watch_child_drain.QUIET_HEARTBEAT_SECONDS_ENV, raising=False)
    monkeypatch.delenv(
        watch_progress_stall.PROGRESS_STALL_SECONDS_ENV,
        raising=False,
    )

    progress_watch = watch_progress_stall.ProgressEmitWatch.start("probe", now=0.0)

    assert progress_watch.stall_seconds == 300.0
    assert (
        watch_child_drain.quiet_heartbeat_seconds(progress_watch.stall_seconds) == 300.0
    )


def _drain(proc, raw_path: Path, *, settle_child: bool = False):
    """Run the drain against *proc*, returning (raw text, summary, emitted).

    With *settle_child*, the first liveness tick waits for the child to
    finish and exit. That tick runs between the select and the check for
    whether the child is gone, so against a child that is silent at first
    it reproduces — without depending on machine timing — the ordering
    that loses output: the select found nothing, and by the time the
    reader asks, the child is dead with its final bytes unread in the pipe.
    """
    emitted: list[str] = []
    ticks = {"count": 0}

    def pump_tick() -> None:
        ticks["count"] += 1
        if settle_child and ticks["count"] == 1:
            proc.wait()

    with raw_path.open("w", encoding="utf-8", buffering=1) as raw_f:
        early, last_summary, timed_out = drain_watched_child(
            proc=proc,
            kind="probe",
            classifier=_classify,
            gate=ProgressGate(ThrottlePolicy()),
            # Batching has its own coverage; this drain asserts ordering,
            # so each carried line comes straight back out.
            digest=ProgressDigest(kind="probe", flush_seconds=0.0),
            raw_f=raw_f,
            progress_f=raw_f,
            out=raw_f,
            emit_immediate=emitted.append,
            pump_tick=pump_tick,
            clock=time.monotonic,
            deadline=None,
            timeout_seconds=None,
            raw_capture=raw_path,
            stall_abort_exit=97,
        )
    assert early is None
    assert not timed_out
    proc.wait()
    return raw_path.read_text(encoding="utf-8"), last_summary, emitted


class TestOutputPendingWhenTheChildExits:
    """The child is gone and its last lines are still in the pipe."""

    def test_the_pending_lines_reach_the_raw_capture(
        self, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.setenv("YOKE_WATCH_QUIET_HEARTBEAT_SECONDS", "0.05")
        proc = _spawn(_QUIET_THEN_OUTCOME)

        raw, _, _ = _drain(proc, tmp_path / "raw.log", settle_child=True)

        assert "SUMMARY verdict=pass" in raw
        assert '{"verdict": "pass"}' in raw

    def test_the_outcome_is_reported_as_the_summary(
        self, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.setenv("YOKE_WATCH_QUIET_HEARTBEAT_SECONDS", "0.05")
        proc = _spawn(_QUIET_THEN_OUTCOME)

        _, last_summary, _ = _drain(proc, tmp_path / "raw.log", settle_child=True)

        assert last_summary is not None
        assert "verdict" in last_summary

    def test_the_pending_lines_are_emitted_not_only_captured(
        self, monkeypatch, tmp_path
    ) -> None:
        """Captured-but-unemitted would still leave the caller blind."""
        monkeypatch.setenv("YOKE_WATCH_QUIET_HEARTBEAT_SECONDS", "0.05")
        proc = _spawn(_QUIET_THEN_OUTCOME)

        _, _, emitted = _drain(proc, tmp_path / "raw.log", settle_child=True)

        assert any("verdict=pass" in line for line in emitted)


class TestOrdinaryOutputIsUnchanged:
    def test_a_quiet_child_read_in_the_usual_order_still_works(
        self, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.setenv("YOKE_WATCH_QUIET_HEARTBEAT_SECONDS", "0.05")
        proc = _spawn(_QUIET_THEN_OUTCOME)

        raw, last_summary, _ = _drain(proc, tmp_path / "raw.log")

        assert "SUMMARY verdict=pass" in raw
        assert '{"verdict": "pass"}' in raw
        assert last_summary is not None

    def test_a_chatty_child_is_captured_in_order(
        self, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.setenv("YOKE_WATCH_QUIET_HEARTBEAT_SECONDS", "5")
        proc = _spawn(
            "import sys\n"
            "for i in range(20):\n"
            "    sys.stdout.write(f'line {i}\\n')\n"
            "sys.stdout.write('SUMMARY done\\n')\n"
            "sys.stdout.flush()\n"
        )

        raw, last_summary, _ = _drain(proc, tmp_path / "raw.log")

        assert raw.splitlines()[:2] == ["line 0", "line 1"]
        assert "line 19" in raw
        assert last_summary is not None
        assert "SUMMARY done" in last_summary
