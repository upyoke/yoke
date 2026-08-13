"""The read schedule every GitHub run poller follows."""

from __future__ import annotations

import pytest

from yoke_core.domain.github_poll_schedule import (
    CI_SUITE_SCHEDULE,
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


class TestCiSuiteShape:
    """Front-loaded probes, a quiet middle, then a steady tail."""

    def test_reads_are_front_loaded_then_quiet_then_steady(self):
        assert read_offsets(CI_SUITE_SCHEDULE, until=660) == [
            0.0, 60.0, 120.0, 180.0, 480.0, 540.0, 600.0, 660.0,
        ]

    def test_no_read_falls_inside_the_quiet_window(self):
        quiet_start = CI_SUITE_SCHEDULE.probe_offsets[-1]
        quiet_end = CI_SUITE_SCHEDULE.quiet_until_seconds
        inside = [
            offset
            for offset in read_offsets(CI_SUITE_SCHEDULE, until=1200)
            if quiet_start < offset < quiet_end
        ]
        assert inside == []

    def test_every_pair_of_reads_respects_the_minimum_interval(self):
        offsets = read_offsets(CI_SUITE_SCHEDULE, until=1800)
        gaps = [b - a for a, b in zip(offsets, offsets[1:])]
        assert min(gaps) >= MINIMUM_POLL_INTERVAL_SECONDS

    def test_a_slow_read_does_not_push_later_reads_back(self):
        # A read that started at 60s and cost 30s leaves the loop at 90s;
        # the next read still lands on the schedule's own 120s offset.
        assert next_read_delay(90.0, CI_SUITE_SCHEDULE) == 30.0


class TestDiscovery:
    """What the schedule costs in latency, at both ends of the profile."""

    def test_a_run_concluding_at_ninety_seconds_is_seen_at_the_next_probe(self):
        concluded_at = 90.0
        first_read_after = next(
            offset
            for offset in read_offsets(CI_SUITE_SCHEDULE, until=1200)
            if offset >= concluded_at
        )
        assert first_read_after == 120.0

    def test_a_run_concluding_at_ten_minutes_is_seen_within_one_interval(self):
        concluded_at = 600.0
        first_read_after = next(
            offset
            for offset in read_offsets(CI_SUITE_SCHEDULE, until=1800)
            if offset >= concluded_at
        )
        assert first_read_after - concluded_at <= MINIMUM_POLL_INTERVAL_SECONDS


class TestSteadySchedule:
    """A run with no known duration floor gets the floor and nothing else."""

    def test_reads_run_at_the_minimum_interval_from_the_start(self):
        assert read_offsets(STEADY_SCHEDULE, until=300) == [
            0.0, 60.0, 120.0, 180.0, 240.0, 300.0,
        ]


class TestScheduleRefusesToBreakTheFloor:
    """The minimum interval is a property of the schedule, not a convention."""

    def test_probes_closer_than_the_minimum_are_refused(self):
        with pytest.raises(ValueError, match="minimum interval"):
            PollSchedule(probe_offsets=(30.0, 60.0))

    def test_a_quiet_window_ending_too_soon_after_a_probe_is_refused(self):
        with pytest.raises(ValueError, match="minimum interval"):
            PollSchedule(probe_offsets=(60.0,), quiet_until_seconds=90.0)

    def test_a_tail_interval_below_the_minimum_is_refused(self):
        with pytest.raises(ValueError, match="minimum interval"):
            PollSchedule(interval_seconds=30.0)
