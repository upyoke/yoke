"""Report diagnostics cannot change decisions or leak across requests."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from yoke_core.domain import steering_fleet_report_timing as timing
from yoke_core.domain.merge_queue_read_reuse import MergeQueueReads
from yoke_core.domain.steering_fleet_report_reads import FleetReportReads


def _records(caplog):
    return [
        r
        for r in caplog.records
        if getattr(r, "event_name", "") == "SteeringReportTiming"
    ]


def test_nested_boundaries_measure_once_and_keep_results(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=timing._LOG.name)
    ticks = iter([1.0, 1.1, 1.3, 1.5])
    monkeypatch.setattr(timing, "perf_counter", lambda: next(ticks))
    expected = object()

    @timing.report_timed("scope", root=True)
    def scope():
        return expected

    @timing.report_timed("compose", root=True)
    def compose(**kwargs):
        return scope()

    assert compose(session_id="test-session") is expected
    (record,) = _records(caplog)
    assert record.session_id == "test-session"
    assert record.context == {
        "operation": "compose",
        "outcome": "completed",
        "phases": {
            "scope": {"duration_ms": 200.0, "calls": 1, "errors": 0},
            "compose": {"duration_ms": 500.0, "calls": 1, "errors": 0},
        },
    }
    assert timing._PHASES.get() is None


def test_failure_is_logged_and_next_request_has_clean_context(caplog):
    caplog.set_level(logging.INFO, logger=timing._LOG.name)
    failure = ValueError("original report error")

    @timing.report_timed("compose", root=True)
    def compose(fail):
        if fail:
            with timing.report_phase("awaiting_seat"):
                raise failure
        return "report"

    with pytest.raises(ValueError) as exc:
        compose(True)
    assert exc.value is failure
    assert compose(False) == "report"
    first, second = _records(caplog)
    assert first.context["outcome"] == "exception"
    assert first.context["phases"]["awaiting_seat"]["errors"] == 1
    assert "awaiting_seat" not in second.context["phases"]
    assert timing._PHASES.get() is None


def test_logging_failure_never_replaces_result_or_report_error(monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("sink unavailable")

    monkeypatch.setattr(timing._LOG, "info", unavailable)

    @timing.report_timed("compose", root=True)
    def compose(fail):
        if fail:
            raise ValueError("report failure")
        return "unchanged"

    assert compose(False) == "unchanged"
    with pytest.raises(ValueError, match="report failure"):
        compose(True)
    assert timing._PHASES.get() is None


def test_only_cache_misses_count_as_reads(caplog):
    caplog.set_level(logging.INFO, logger=timing._LOG.name)
    calls = []

    @timing.report_timed("compose", root=True)
    def compose():
        facts, github = FleetReportReads(), MergeQueueReads()
        for _ in range(3):
            facts.cached(("project_slug", 1), lambda: calls.append("db"))
            github._read(
                ("queue_members", "test", "main"), lambda: calls.append("github")
            )

    compose()
    assert calls == ["db", "github"]
    phases = _records(caplog)[0].context["phases"]
    assert phases["read.project_slug"]["calls"] == 1
    assert phases["github.queue_members"]["calls"] == 1


def test_concurrent_reports_do_not_share_phases(caplog):
    caplog.set_level(logging.INFO, logger=timing._LOG.name)
    barrier = Barrier(2)

    @timing.report_timed("compose", root=True)
    def compose(*, session_id):
        with timing.report_phase(session_id):
            barrier.wait(timeout=5)
        return session_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(compose, session_id=name) for name in ("first", "second")
        ]
        assert [f.result() for f in futures] == ["first", "second"]
    records = _records(caplog)
    assert len(records) == 2
    for record in records:
        assert set(record.context["phases"]) == {"compose", record.session_id}


def test_sections_outside_report_do_not_log_or_read_clock(monkeypatch, caplog):
    def unexpected():
        raise AssertionError("clock read outside report")

    monkeypatch.setattr(timing, "perf_counter", unexpected)
    with timing.report_phase("github.queue_members"):
        pass
    assert not _records(caplog)
