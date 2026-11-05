# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import io

from datetime import datetime, timedelta, timezone

from types import SimpleNamespace

from yoke_core.domain.fleet_delta_reports import ReportState, append_steering_reports

from yoke_core.domain.fleet_delta_snapshot import STEERING_REPORT_FUNCTION

from yoke_core.domain.steering_fleet_report_render import REPORT_BEGIN, REPORT_END

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
