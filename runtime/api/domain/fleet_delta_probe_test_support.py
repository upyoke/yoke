# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import io

import json

from datetime import datetime, timedelta, timezone

from types import SimpleNamespace

from typing import Any

import pytest

from yoke_core.domain import fleet_delta_probe

from yoke_core.domain.fleet_delta_probe import (
    DEFER_TO_REPORT,
    MAX_CONSECUTIVE_READ_FAILURES,
    READ_FAILURE_EXIT,
    WAKE_NOW,
    delta_wake_tier,
    run,
)

from yoke_core.domain.fleet_delta_reports import PROJECT_POLICY_FUNCTION

from yoke_core.domain.fleet_delta_snapshot import (
    STEERING_REPORT_FUNCTION,
    ENVELOPES_FUNCTION,
    FRONTIER_FUNCTION,
    SESSIONS_FUNCTION,
)

from yoke_core.domain.steering_fleet_report_render import REPORT_BEGIN, REPORT_END

NOW = datetime(2026, 8, 28, 17, 0, tzinfo=timezone.utc)

REPORT_BODY = f"{REPORT_BEGIN}\nproject 1\n  one composed picture\n{REPORT_END}"

REPORT_DIGEST = (
    f"{REPORT_BEGIN}\n"
    "composed 2026-08-28T17:00:00Z · 1 held scopes · hook digest\n"
    "one composed picture\n"
    f"{REPORT_END}"
)


def _ok(result: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(success=True, result=result, error=None)


def _policy(interval_minutes: int = 2) -> SimpleNamespace:
    return _ok(
        {
            "settings_json": json.dumps(
                {"steering_report_interval_minutes": interval_minutes}
            )
        }
    )


def _report(
    fingerprint: str = "fleet-a", digest: str = REPORT_DIGEST
) -> SimpleNamespace:
    return _ok({"fingerprint": fingerprint, "digest": digest, "body": REPORT_BODY})


class _Clock:
    """Advances one interval per read so a bounded run terminates."""

    def __init__(self, step_seconds: int = 60) -> None:
        self.now = NOW
        self.step = timedelta(seconds=step_seconds)

    def __call__(self) -> datetime:
        current = self.now
        self.now += self.step
        return current
