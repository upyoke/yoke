"""The read schedule every GitHub run poller follows."""

from __future__ import annotations

import pytest

from yoke_core.domain.github_poll_schedule import (
    MINIMUM_POLL_INTERVAL_SECONDS,
    STEADY_SCHEDULE,
    PollSchedule,
    next_read_delay,
)


def read_offsets(schedule: PollSchedule, *, until: float) -> list[float]:
    """Every offset a poll loop on *schedule* reads at, up to *until*."""
    offsets = [0.0]
    while offsets[-1] < until:
        offsets.append(offsets[-1] + next_read_delay(offsets[-1], schedule))
    return offsets


class TestSteadySchedule:
    """Every run is read once a minute from the start."""

    def test_reads_stay_steady_through_the_first_eleven_minutes(self):
        assert read_offsets(STEADY_SCHEDULE, until=660) == [
            float(offset) for offset in range(0, 661, 60)
        ]

    def test_every_pair_of_reads_respects_the_minimum_interval(self):
        offsets = read_offsets(STEADY_SCHEDULE, until=1800)
        gaps = [b - a for a, b in zip(offsets, offsets[1:])]
        assert min(gaps) >= MINIMUM_POLL_INTERVAL_SECONDS

    def test_a_slow_read_does_not_push_later_reads_back(self):
        assert next_read_delay(90.0, STEADY_SCHEDULE) == 30.0


@pytest.mark.parametrize("concluded_at", [90.0, 181.0, 241.0, 301.0, 421.0, 600.0])
def test_completion_is_seen_within_one_interval(concluded_at):
    first_read_after = next(
        offset
        for offset in read_offsets(STEADY_SCHEDULE, until=1200)
        if offset >= concluded_at
    )
    assert first_read_after - concluded_at < MINIMUM_POLL_INTERVAL_SECONDS


class TestScheduleRefusesToBreakTheFloor:
    """The minimum interval is a property of the schedule, not a convention."""

    def test_an_interval_below_the_minimum_is_refused(self):
        with pytest.raises(ValueError, match="minimum interval"):
            PollSchedule(interval_seconds=30.0)


def test_a_schedule_describes_its_cadence_for_a_designed_wait() -> None:
    assert STEADY_SCHEDULE.describe() == "checks every 60s"


@pytest.mark.parametrize("caller", ["commit_watch", "monitoring", "qa_case", "cli"])
def test_ci_wait_callers_read_through_the_former_gap(monkeypatch, caller):
    from contextlib import nullcontext
    from types import SimpleNamespace

    from yoke_cli.commands.adapters import github_actions_wait as cli
    from yoke_core.domain import (
        deploy_pipeline_reporting as reporting,
        github_actions_commit_run_watch as watch,
        github_actions_run_monitoring as monitoring,
        qa_case_ci_lane as qa,
    )

    elapsed = 0.0
    reads = []

    def now():
        return elapsed

    def sleep(seconds):
        nonlocal elapsed
        elapsed += seconds

    def run():
        reads.append(elapsed)
        done = elapsed >= 300
        return {"id": 1, "status": "completed" if done else "in_progress",
                "conclusion": "success" if done else None}

    if caller == "commit_watch":
        assert watch.watch_commit_runs(
            head_sha="a" * 40, ref="HEAD", repo="owner/repo", workflow_name="",
            fetch_runs=lambda: [run()], emit=lambda line: None,
            now=now, sleep=sleep,
        ) == 0
    elif caller == "monitoring":
        with pytest.raises(SystemExit) as result:
            monitoring.check_ci_command(
                "owner/repo", "ci", branch="main", wait=True, timeout_sec=600,
                check_auth=lambda: None, get_latest_run=run, now=now, sleep=sleep,
            )
        assert result.value.code == 0
    elif caller == "qa_case":
        def poll(*args, **kwargs):
            state = run()
            return SimpleNamespace(
                returncode=0 if state["status"] == "completed" else 2,
                stdout=state["status"], stderr="",
            )

        monkeypatch.setattr(reporting, "_github_actions", poll)
        monkeypatch.setattr(reporting.time, "time", now)
        monkeypatch.setattr(reporting.time, "sleep", sleep)
        monkeypatch.setattr(qa, "relay_poll_output", nullcontext)
        assert qa.await_workflow(
            project="example", repo="owner/repo", run_id="1", timeout_seconds=600,
        ) == (0, "completed")
    else:
        # The CLI adapter loads the shared schedule at its client boundary.
        while elapsed <= 300:
            reads.append(elapsed)
            sleep(cli._next_read_delay(int(elapsed)))
        assert cli._ci_cadence() == "checks every 60s"

    assert reads == [0, 60, 120, 180, 240, 300]
