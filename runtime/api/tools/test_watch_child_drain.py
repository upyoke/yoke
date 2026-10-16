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
    'sys.stdout.write(\'{"verdict": "pass"}\\n\')\n'
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

    def test_a_chatty_child_is_captured_in_order(self, monkeypatch, tmp_path) -> None:
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


class TestDesignedWaitAnnouncementsReachTheReader:
    """The line that explains a coming silence is never left in raw only."""

    _LINE = "Waiting by design: CI checks; gives up after 15m.\n"

    def _route(self, tmp_path: Path, *, outcome_only: bool) -> list[str]:
        emitted: list[str] = []
        with (tmp_path / "raw.log").open("w", encoding="utf-8") as raw_f:
            watch_child_drain._route_line(
                self._LINE,
                now=0.0,
                classifier=lambda _line: Classification(LineClass.NOISE),
                gate=ProgressGate(ThrottlePolicy()),
                digest=ProgressDigest(kind="probe", flush_seconds=0.0),
                raw_f=raw_f,
                progress_watch=watch_progress_stall.ProgressEmitWatch.start(
                    "probe", now=0.0
                ),
                emit_immediate=emitted.append,
                outcome_only=outcome_only,
            )
        assert self._LINE in (tmp_path / "raw.log").read_text(encoding="utf-8")
        return emitted

    def test_a_standard_watcher_emits_it_immediately(self, tmp_path) -> None:
        assert self._route(tmp_path, outcome_only=False) == [self._LINE]

    def test_an_outcome_only_watcher_still_emits_it(self, tmp_path) -> None:
        assert self._route(tmp_path, outcome_only=True) == [self._LINE]


class _Clock:
    """Frozen clock so a test can close the digest window itself."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, delta: float) -> None:
        self.t += delta


def _route_timing(
    line: str,
    *,
    outcome_only: bool,
    digest: ProgressDigest,
    clock: _Clock,
    emitted: list[str],
    raw,
):
    from yoke_core.tools.watch_preflight import classify_preflight_line

    watch_child_drain._route_line(
        line,
        now=clock(),
        classifier=classify_preflight_line,
        gate=ProgressGate(ThrottlePolicy()),
        digest=digest,
        raw_f=raw,
        progress_watch=watch_progress_stall.ProgressEmitWatch.start(
            "deploy", now=clock()
        ),
        emit_immediate=emitted.append,
        outcome_only=outcome_only,
    )


def test_outcome_only_bounds_ok_timing_lines_and_emits_failures():
    import io

    clock = _Clock()
    digest = ProgressDigest(kind="deploy", flush_seconds=100.0, time_source=clock)
    emitted: list[str] = []
    raw = io.StringIO()
    opening = 'Deployment start timing: {"outcome": "ok", "step": "restore"}\n'
    held = 'Deployment start timing: {"outcome": "pending", "step": "copy"}\n'
    closing = 'Deployment start timing: {"outcome": "ok", "step": "boot"}\n'
    failed = 'Deployment start timing: {"outcome": "failed", "step": "copy"}\n'
    _route_timing(
        opening, outcome_only=True, digest=digest, clock=clock, emitted=emitted, raw=raw
    )
    assert emitted == ["# watch_deploy digest: " + opening.strip() + "\n"]
    emitted.clear()
    clock.advance(10.0)
    _route_timing(
        held, outcome_only=True, digest=digest, clock=clock, emitted=emitted, raw=raw
    )
    assert emitted == []
    clock.advance(100.0)
    _route_timing(
        closing, outcome_only=True, digest=digest, clock=clock, emitted=emitted, raw=raw
    )
    assert len(emitted) == 1
    assert emitted[0].startswith("# watch_deploy digest: ")
    assert "copy" in emitted[0] and "boot" in emitted[0]
    assert not any(line.startswith("Deployment start timing:") for line in emitted)
    emitted.clear()
    _route_timing(
        failed, outcome_only=True, digest=digest, clock=clock, emitted=emitted, raw=raw
    )
    assert emitted == [failed]
    text = raw.getvalue()
    for line in (opening, held, closing, failed):
        assert line in text


def test_standard_watcher_still_emits_timing_lines_as_they_arrive():
    import io

    clock = _Clock()
    digest = ProgressDigest(kind="preflight", flush_seconds=100.0, time_source=clock)
    emitted: list[str] = []
    raw = io.StringIO()
    line = 'Deployment start timing: {"outcome": "ok", "step": "restore"}\n'
    _route_timing(
        line, outcome_only=False, digest=digest, clock=clock, emitted=emitted, raw=raw
    )
    assert emitted == [line]
    assert raw.getvalue() == line
