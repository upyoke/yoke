# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.timestamps import parse_instant

from yoke_contracts.session_control.extra_usage import (
    EXTRA_AVAILABLE,
    extra_usage,
)

from yoke_contracts.session_control.models import (
    LaunchCreateRequest,
    LaunchPreviewRequest,
)

from yoke_core.domain.handlers import session_launch as handlers

from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility

from yoke_core.domain.session_launch_level_placement import LEVEL_NO_CAPACITY

from yoke_core.domain.session_launch_level_selection import preview_level_launch

from yoke_core.domain.session_launch_projection import public_launch_record

from yoke_core.domain.session_launch_requests import create_launch, retry_launch

from yoke_core.domain.session_launch_store import get_launch, update_launch

from yoke_core.domain.session_launch_types import LaunchRequest, SessionLaunchError

from runtime.api.domain.session_launch_level_test_support import (
    CLAUDE_OPUS,
    CODEX_SOL,
    EXTRA_OFF,
    LEVEL,
    add_surface,
    level_connection,
    pin_live_workers,
    plan_reading,
    weekly,
)

from runtime.api.domain.session_launch_test_support import (
    NOW,
    assigned_launch,
    authorization,
)

from runtime.api.domain.session_launch_handler_deadlines_test_support import (
    _request,
    _wire_handler,
)

NO_EXTRA = EXTRA_OFF


def _meters(
    conn, machine_id: str, surface: str, remaining: float, extra=NO_EXTRA
) -> None:
    conn.execute(
        "UPDATE session_relays SET surface_plan_limits = ? WHERE relay_id = ?",
        (
            json.dumps({surface: plan_reading([weekly(remaining)], extra)}),
            f"relay-{machine_id}-{surface}",
        ),
    )
    conn.commit()


def _two_options(*, claude: float, codex: float, codex_extra=NO_EXTRA):
    conn = level_connection(CODEX_SOL, CLAUDE_OPUS)
    add_surface(conn, "m-codex", "codex-cli", [weekly(codex)], codex_extra)
    add_surface(conn, "m-claude", "claude-cli", [weekly(claude)], NO_EXTRA)
    return conn


def _level_request(key: str = "level-key", level: str = LEVEL) -> LaunchRequest:
    return LaunchRequest(
        project_id=10,
        executor_surface="",
        instructions="Report the current evidence.",
        idempotency_key=key,
        level=level,
    )
