"""Placement filters impossible pairs and reports unreadable quota."""

import json
from io import StringIO

import pytest

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility
from yoke_core.domain.session_launch_level_placement import place_level
from yoke_core.domain.session_launch_level_pools import PoolCheck
from yoke_cli.commands.adapters.session_control_level_placement_output import (
    write_level_candidates,
)
from runtime.api.domain.session_launch_level_test_support import (
    CLAUDE_OPUS,
    CODEX_SOL,
    LEVEL,
    add_surface,
    level_connection,
    pin_live_workers,
    weekly,
)
from runtime.api.domain.session_launch_test_support import NOW, authorization


def place(conn):
    return place_level(
        conn,
        auth=authorization(actor_id=1),
        project_id=10,
        level=LEVEL,
        machine_id=None,
        now=parse_instant(NOW),
        eligibility=derive_launch_eligibility,
    )


@pytest.fixture(autouse=True)
def workers(monkeypatch):
    pin_live_workers(monkeypatch, {})


def test_claude_is_eligible_with_quota_and_no_listing_adapter():
    conn = level_connection(CLAUDE_OPUS, CODEX_SOL)
    add_surface(conn, "claude-machine", "claude-cli", [weekly(80)])
    conn.execute(
        "UPDATE session_relays SET surface_native_models = ?",
        (
            json.dumps(
                {
                    "claude-cli": {
                        "status": "unsupported",
                        "reason": "no native adapter",
                        "models": [],
                    }
                }
            ),
        ),
    )
    result = place(conn)
    assert result.chosen.surface == "claude-cli"
    assert result.chosen.model == CLAUDE_OPUS["model"]
    assert result.chosen.pools[0].remaining_percent == 80
    assert not any(
        candidate.surface == "claude-cli" and candidate.model == CODEX_SOL["model"]
        for candidate in result.candidates
    )
    assert not any(
        candidate.surface == "codex-cli" and candidate.model == CLAUDE_OPUS["model"]
        for candidate in result.candidates
    )


def test_quota_failure_names_reason_and_recovery_without_exhaustion():
    conn = level_connection(CLAUDE_OPUS)
    add_surface(
        conn,
        "claude-machine",
        "claude-cli",
        [
            {
                "window_kind": "unknown",
                "scope": "all",
                "meter": "unknown",
                "remaining_percent": None,
                "resets_at": None,
                "status": "unknown",
                "reason": "stale_credential",
            }
        ],
    )
    result = place(conn)
    assert result.chosen is not None
    pool = result.to_dict()["chosen"]["pools"][0]
    assert pool["reason"] == "stale_credential"
    assert "re-authenticate" in pool["guidance"]
    assert not pool["exhausted"]
    output = StringIO()
    write_level_candidates(result.to_dict(), output)
    assert "stale_credential" in output.getvalue()
    assert "re-authenticate" in output.getvalue()


def test_pool_projection_preserves_null_reset_and_opaque_window():
    pool = PoolCheck(
        "opaque .123+offset", None, None, None, "unknown", False, "http_429"
    )
    assert json.loads(json.dumps(pool.to_dict())) == {
        "window": "opaque .123+offset",
        "remaining_percent": None,
        "headroom_percent": None,
        "resets_at": None,
        "resets_utc": None,
        "status": "unknown",
        "exhausted": False,
        "reason": "http_429",
        "workers": 0,
        "extra_status": "unknown",
        "extra_label": "",
        "share_percent": None,
        "guidance": "the vendor throttled the limits check; the surface is not known to be signed out; it retries on the next refresh",
    }
