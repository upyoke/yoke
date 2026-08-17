"""Hook health beside the Overview's harness activation targets.

Colours say what the operator should do: green when hook-fed telemetry
is present, orange when approval is readable and untrusted, red when
listed and not yet working after the new-episode grace window. Grey is
not a colour — a harness with no evidence and no matching session is
omitted.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_contracts.harness_hook_approval import HARNESS_HOOK_APPROVAL
from yoke_core.domain.overview_harness_hook_health import (
    HOOK_HEALTH_GREEN,
    HOOK_HEALTH_ORANGE,
    HOOK_HEALTH_RED,
    NEW_EPISODE_GRACE,
    harness_targets,
    session_identities,
)


def _by_key(identities, reports=None, *, now=None):
    return {
        target["key"]: target
        for target in harness_targets(identities, reports, now=now)
    }


def _old_episode():
    return (datetime.now(timezone.utc) - NEW_EPISODE_GRACE - timedelta(seconds=1)).isoformat()


def test_sessions_without_telemetry_report_red_after_grace():
    targets = _by_key(session_identities([
        ("codex", "codex-desktop", 0, _old_episode(), None),
    ]))

    assert targets["codex"]["hit"] is True
    assert targets["codex"]["hook_health"] == HOOK_HEALTH_RED
    assert targets["codex"]["trust_surface"] == (
        HARNESS_HOOK_APPROVAL["codex"]["trust_surface"]
    )
    assert "claude-code" not in targets
    assert "cursor" not in targets


def test_one_session_with_hook_telemetry_reports_green():
    targets = _by_key(session_identities([
        ("codex", "codex-desktop", 0, _old_episode(), None),
        ("codex", "", 2, _old_episode(), None),
    ]))

    assert targets["codex"]["hook_health"] == HOOK_HEALTH_GREEN
    assert targets["codex-cli"]["hook_health"] == HOOK_HEALTH_GREEN


def test_unapproved_report_is_orange_without_a_harness_id_branch():
    targets = _by_key(
        [],
        reports=[{
            "harness_id": "codex",
            "glue_present": True,
            "config_present": True,
            "approval_state": "unapproved",
        }],
    )

    assert targets["codex"]["hook_health"] == HOOK_HEALTH_ORANGE
    assert targets["codex"]["hit"] is False


def test_fresh_episode_without_telemetry_stays_uncoloured():
    now = datetime.now(timezone.utc)
    targets = _by_key(
        session_identities([
            ("codex", "codex-desktop", 0, now.isoformat(), None),
        ]),
        now=now,
    )

    assert targets["codex"]["hit"] is True
    assert targets["codex"]["hook_health"] is None


def test_claude_lists_from_a_session_and_has_no_trust_surface():
    targets = _by_key(session_identities([
        ("claude-code", "claude-desktop", 1, _old_episode(), None),
    ]))

    assert targets["claude-code"]["hook_health"] == HOOK_HEALTH_GREEN
    assert targets["claude-code"]["trust_surface"] is None
    assert "claude-code" not in HARNESS_HOOK_APPROVAL
