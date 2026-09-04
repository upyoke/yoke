"""Hook health beside the Overview's harness activation targets.

Colours say what the operator should do: green for recent telemetry, orange
for an installed surface without recent telemetry, and red for a current
silent session or explicitly unapproved hooks. A brand-new silent episode
stays uncoloured during its grace window.
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

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def _at(age: timedelta = timedelta()) -> str:
    return (NOW - age).isoformat()


def _identities(
    executor: str,
    surface: str,
    *,
    telemetry: int = 0,
    seen_at: str | None = None,
    episode_started_at: str | None = None,
):
    seen = seen_at or _at()
    return session_identities([(
        executor,
        surface,
        telemetry,
        episode_started_at or seen,
        None,
        seen,
    )])


def _by_key(identities, reports=None, *, installed=None, now=NOW):
    return {
        target["key"]: target
        for target in harness_targets(
            identities,
            reports,
            installed_surfaces=installed,
            now=now,
        )
    }


def test_current_session_without_telemetry_reports_red_after_grace():
    seen = _at(NEW_EPISODE_GRACE + timedelta(seconds=1))
    targets = _by_key(_identities("codex", "codex-desktop", seen_at=seen))

    assert targets["codex"]["hit"] is True
    assert targets["codex"]["hook_health"] == HOOK_HEALTH_RED
    assert targets["codex"]["trust_surface"] is None
    assert "claude-code" not in targets
    assert "cursor" not in targets


def test_recent_hook_telemetry_reports_green():
    targets = _by_key(_identities(
        "codex", "codex-desktop", telemetry=2,
    ))

    assert targets["codex"]["hook_health"] == HOOK_HEALTH_GREEN


def test_claude_cli_matches_its_surface_alias_and_not_a_bare_row():
    aliased = _by_key(_identities(
        "claude-code", "claude-cli", telemetry=1,
    ))
    bare = _by_key(_identities("claude-code", "", telemetry=1))

    assert aliased["claude-cli"]["hook_health"] == HOOK_HEALTH_GREEN
    assert "claude-cli" not in bare


def test_codex_cli_matches_its_surface_alias_and_not_a_bare_row():
    aliased = _by_key(_identities("codex", "codex-cli", telemetry=1))
    bare = _by_key(_identities("codex", "", telemetry=1))

    assert aliased["codex-cli"]["hook_health"] == HOOK_HEALTH_GREEN
    assert "codex-cli" not in bare


def test_unapproved_report_is_red_and_names_its_trust_surface():
    targets = _by_key(
        [],
        reports=[{
            "harness_id": "codex",
            "glue_present": True,
            "config_present": True,
            "approval_state": "unapproved",
        }],
    )

    assert targets["codex"]["hook_health"] == HOOK_HEALTH_RED
    assert targets["codex"]["hit"] is False
    assert targets["codex"]["trust_surface"] == (
        HARNESS_HOOK_APPROVAL["codex"]["trust_surface"]
    )


def test_fresh_episode_without_telemetry_stays_uncoloured():
    targets = _by_key(_identities("codex", "codex-desktop"))

    assert targets["codex"]["hit"] is True
    assert targets["codex"]["hook_health"] is None


def test_installed_surface_never_seen_is_orange():
    targets = _by_key([], installed=["claude-vscode"])

    assert targets["claude-vscode"]["hit"] is False
    assert targets["claude-vscode"]["hook_health"] == HOOK_HEALTH_ORANGE
    assert targets["claude-vscode"]["last_seen_at"] is None


def test_installed_surface_seen_five_weeks_ago_is_orange_with_last_seen():
    last_seen = _at(timedelta(weeks=5))
    targets = _by_key(
        _identities(
            "claude-code", "claude-vscode", telemetry=1, seen_at=last_seen,
        ),
        installed=["claude-vscode"],
    )

    assert targets["claude-vscode"]["hit"] is True
    assert targets["claude-vscode"]["hook_health"] == HOOK_HEALTH_ORANGE
    assert targets["claude-vscode"]["last_seen_at"] == last_seen


def test_claude_has_no_hook_trust_surface():
    targets = _by_key(_identities(
        "claude-code", "claude-desktop", telemetry=1,
    ))

    assert targets["claude-code"]["hook_health"] == HOOK_HEALTH_GREEN
    assert targets["claude-code"]["trust_surface"] is None
    assert "claude-code" not in HARNESS_HOOK_APPROVAL
