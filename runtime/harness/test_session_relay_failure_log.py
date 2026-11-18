"""The relay failure reporter logs a burst once, periodically, and on recovery."""

from __future__ import annotations

from datetime import datetime, timezone
import logging


def test_failure_burst_logs_first_periodic_and_recovery_lines(caplog) -> None:
    import yoke_harness.session_relay_failure_log as failure_log

    interval = failure_log.FAILURE_LOG_INTERVAL_SECONDS
    observed = iter((0.0, 10.0, float(interval), float(interval + 5)))
    stamp = datetime(2026, 9, 8, 14, 54, 9, tzinfo=timezone.utc)
    reporter = failure_log.FailureReporter(
        interval_seconds=interval,
        clock=lambda: next(observed),
        stamp_clock=lambda: stamp,
    )
    caplog.set_level(logging.WARNING, logger=failure_log.__name__)

    reporter.failed("poll", "request rejected")
    reporter.failed("poll", "request rejected")
    reporter.failed("poll", "request rejected")
    reporter.recovered("poll")

    messages = [record.getMessage() for record in caplog.records]
    assert messages == [
        "2026-09-08T14:54:09.000000Z relay poll failed: request rejected; "
        "class=relay_failure consecutive_failures=1 elapsed_seconds=0.0 "
        "outcome=retrying",
        "2026-09-08T14:54:09.000000Z relay poll failed: request rejected; "
        "class=relay_failure consecutive_failures=3 "
        f"elapsed_seconds={interval:.1f} outcome=retrying",
        "2026-09-08T14:54:09.000000Z relay poll recovered; class=relay_recovery "
        "consecutive_failures=3 "
        f"elapsed_seconds={interval + 5:.1f} outcome=recovered",
    ]
