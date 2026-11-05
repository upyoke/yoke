# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from datetime import datetime, timedelta, timezone

import pytest

from yoke_contracts.timestamps import format_instant, parse_instant

from yoke_core.domain.events_tool_call_outcome import OUTCOME_INTERRUPTED

from yoke_core.domain.sessions import (
    claim_work,
    end_session,
    end_session_if_empty,
)

from yoke_core.domain.sessions_orphan_tool_call_sweep import (
    LIFECYCLE_REASONS,
    OrphanSweepReason,
    build_sentinel_reason,
    sweep_orphaned_tool_calls,
)

from runtime.api.sessions_orphan_sweep_test_schema import _seed_events

from runtime.api.sessions_test_support import _insert_claimable_item, _register


def _now_iso(offset_s: int = 0) -> str:
    when = datetime.now(timezone.utc) + timedelta(seconds=offset_s)
    return format_instant(when)


def _insert_open_call(c, *, session_id, tool_use_id, tool_name="Bash", started_at=None):
    """Open a session_tool_calls row (what observe_pre records on Started)."""
    started_at = started_at or _now_iso()
    c.execute(
        """INSERT INTO session_tool_calls
           (session_id, tool_use_id, tool_name, started_at)
           VALUES (%s, %s, %s, %s)""",
        (session_id, tool_use_id, tool_name, started_at),
    )
    c.commit()


def _close_call(c, *, session_id, tool_use_id, outcome="completed"):
    """Close the row (what the observe pipeline does on Completed/Failed)."""
    c.execute(
        """UPDATE session_tool_calls SET completed_at = %s, outcome = %s
           WHERE session_id = %s AND tool_use_id = %s""",
        (_now_iso(), outcome, session_id, tool_use_id),
    )
    c.commit()
