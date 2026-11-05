# ruff: noqa: E402, F401, F811
"""Shared setup for tests in this directory."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime.api.sessions_test_support import _register, conn

from yoke_core.domain.sessions import (
    EVENT_HARNESS_SESSION_STALE_SWEEP_COMPLETED,
    clean_stale_harness_sessions,
)

from yoke_core.domain.sessions_analytics_core import (
    DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES,
)

from runtime.api.sessions_api_stale_test_helpers import (
    EVENTS_TABLE_FOR_STALE_DETECTION,
    _ago_minutes,
    apply_ddl_statements,
)
