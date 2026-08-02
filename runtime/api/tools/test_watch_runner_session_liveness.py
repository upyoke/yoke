"""The watcher keeps its owning session live for the length of the run.

Every long command in Yoke — a registered Command case, a watched suite —
runs through this one runner, so this is where "the run is still going"
becomes an activity signal the stale-session sweep can see.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from yoke_core.tools import _watch_runner
from yoke_core.tools._watch_throttle import Classification, LineClass


class _CountingPump:
    def __init__(self) -> None:
        self.ticks = 0

    def tick(self) -> bool:
        self.ticks += 1
        return False


def _run(tmp_path: Path, argv: list[str], pump: _CountingPump) -> int:
    return _watch_runner.run_watcher(
        argv=argv,
        classifier=lambda _line: Classification(LineClass.NOISE),
        raw_capture=tmp_path / "raw.log",
        progress_capture=tmp_path / "progress.log",
        kind="pytest",
        stdout_stream=io.StringIO(),
        liveness=pump,
    )


def test_a_chatty_run_is_ticked_while_it_streams(tmp_path: Path) -> None:
    pump = _CountingPump()
    exit_code = _run(
        tmp_path,
        [sys.executable, "-c", "print('a')\nprint('b')\nprint('c')"],
        pump,
    )

    assert exit_code == 0
    assert pump.ticks > 0


def test_a_quiet_run_is_ticked_while_it_waits(tmp_path: Path, monkeypatch) -> None:
    # A suite that produces no output for a stretch is exactly the case
    # that used to go stale; the quiet branch has to tick too.
    monkeypatch.setenv(_watch_runner.QUIET_HEARTBEAT_SECONDS_ENV, "0.05")
    pump = _CountingPump()
    exit_code = _run(
        tmp_path,
        [sys.executable, "-c", "import time; time.sleep(0.3)"],
        pump,
    )

    assert exit_code == 0
    assert pump.ticks > 1


def test_the_runner_supplies_its_own_pump_by_default(tmp_path: Path) -> None:
    # Production callers pass nothing; liveness must not be opt-in.
    exit_code = _watch_runner.run_watcher(
        argv=[sys.executable, "-c", "print('done')"],
        classifier=lambda _line: Classification(LineClass.NOISE),
        raw_capture=tmp_path / "raw.log",
        progress_capture=tmp_path / "progress.log",
        kind="pytest",
        stdout_stream=io.StringIO(),
    )

    assert exit_code == 0
