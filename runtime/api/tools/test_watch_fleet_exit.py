"""Fleet exits teach a fresh pair before the follower's final sentinel."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from yoke_core.domain import fleet_delta_probe
from yoke_core.tools import watch_fleet, watch_tail


@pytest.mark.parametrize(
    ("failure", "expected_code", "reason"),
    [
        (False, 0, "reached its 8h duration limit"),
        (True, 1, "stopped after consecutive read failures"),
    ],
)
def test_probe_exit_reaches_the_follower_with_rearm(
    monkeypatch, tmp_path: Path, failure: bool, expected_code: int, reason: str
) -> None:
    script = tmp_path / "probe.py"
    script.write_text(
        "from datetime import datetime, timedelta, timezone\n"
        "from yoke_core.domain import fleet_delta_probe as p\n"
        "from yoke_core.domain.fleet_delta_snapshot import FleetReadError, FleetSnapshot\n"
        "now = datetime.now(timezone.utc)\n"
        "ticks = iter([now, now + timedelta(seconds=p.DEFAULT_DURATION_SECONDS)] * 4)\n"
        "def read(*args, **kwargs):\n"
        + (
            "    raise FleetReadError('sessions.list', 'unreachable')\n"
            if failure
            else "    return FleetSnapshot(taken_at=now, self_session_id='test')\n"
        )
        + "p.read_snapshot = read\n"
        "p._append_steering_reports = lambda *args, **kwargs: None\n"
        "raise SystemExit(p.run(['yoke', 'platform'], duration="
        + ("0" if failure else "p.DEFAULT_DURATION_SECONDS")
        + ", clock=lambda: next(ticks), sleep=lambda _: None, session_id='test'))\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        watch_fleet, "_probe_argv", lambda args: [sys.executable, str(script)]
    )
    progress = tmp_path / "progress.log"
    code = watch_fleet.main(
        [
            "--raw-capture",
            str(tmp_path / "raw.log"),
            "--progress-capture",
            str(progress),
            "--",
            "--project",
            "yoke",
            "--project",
            "platform",
        ]
    )
    assert code == expected_code
    out = io.StringIO()
    assert watch_tail.follow(progress, out=out, poll_interval=0.01) == 0
    lines = out.getvalue().splitlines()
    assert reason in lines[-2]
    assert (
        "`yoke watch fleet --print-streaming-pair -- --project yoke --project platform`"
        in lines[-2]
    )
    assert lines[-1].startswith(f"# watch_fleet exit={expected_code} ")


def test_default_lifetime_and_unbounded_override() -> None:
    assert fleet_delta_probe.DEFAULT_DURATION_SECONDS == 8 * 60 * 60
    assert (
        fleet_delta_probe._parse_args([]).duration
        == fleet_delta_probe.DEFAULT_DURATION_SECONDS
    )
    assert fleet_delta_probe._parse_args(["--duration", "0"]).duration == 0


def test_interrupt_notice_precedes_the_sentinel(monkeypatch, tmp_path: Path) -> None:
    from yoke_core.domain import process_group_reaping

    def interrupt(**kwargs):
        raise process_group_reaping.ProcessGroupInterrupted(2)

    monkeypatch.setattr(watch_fleet._watch_runner, "drain_watched_child", interrupt)
    monkeypatch.setattr(
        watch_fleet, "_probe_argv", lambda args: [sys.executable, "-c", "pass"]
    )
    progress = tmp_path / "progress.log"
    assert (
        watch_fleet.main(
            [
                "--raw-capture",
                str(tmp_path / "raw.log"),
                "--progress-capture",
                str(progress),
                "--",
                "--project",
                "yoke",
            ]
        )
        == 130
    )
    lines = progress.read_text().splitlines()
    assert "interrupted by signal 2" in lines[-2]
    assert "`yoke watch fleet --print-streaming-pair -- --project yoke`" in lines[-2]
    assert lines[-1].startswith("# watch_fleet exit=130 ")
