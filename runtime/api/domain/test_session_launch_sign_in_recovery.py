"""A launch that never registers names its harness's sign-in command.

A signed-out interactive CLI waits on its login screen instead of exiting, so
neither the native's exit nor its silence says why it never registered. Both
unregistered closures therefore carry the surface's own sign-in step, phrased
as a possibility rather than a verdict.
"""

from __future__ import annotations

import json

import pytest

from yoke_contracts.harness_cli_manifest import HARNESS_CLI_MANIFESTS
from yoke_core.domain.session_launch_deadlines import settle_launch_deadlines
from yoke_core.domain.session_launch_execution import (
    claim_assigned_launch,
    report_launch_attempt,
)
from yoke_core.domain.session_launch_store import get_launch
from yoke_core.domain.session_launch_unregistered_death import (
    apply_unregistered_native_death_reports,
)
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    launch_connection,
)

SIGN_IN = {
    "claude-cli": "Run `claude auth login`.",
    "codex-cli": "Run `codex login`.",
    "cursor-cli": "Run `cursor-agent login`.",
}


def _awaiting_registration(surface: str):
    conn = launch_connection()
    add_relay(conn, surface=surface, version="9999.99.99")
    launch = assigned_launch(conn, key=f"sign-in-{surface}", surface=surface, model=None)
    claim = claim_assigned_launch(
        conn,
        launch_id=launch.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now=NOW,
    )
    awaiting = report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="native_created",
        native_session_id=f"native-{surface}",
        now="2026-08-22T12:00:30Z",
    )
    assert awaiting.state == "awaiting_registration"
    return conn, awaiting


def _recovery(conn, launch_id: str) -> str:
    evidence = json.loads(get_launch(conn, launch_id).result_evidence)
    return evidence["sign_in_recovery"]


def _manifest(surface: str):
    return next(m for m in HARNESS_CLI_MANIFESTS if m.surface_id == surface)


@pytest.mark.parametrize("surface", sorted(SIGN_IN))
def test_launch_death_names_the_harness_sign_in(surface):
    conn, launch = _awaiting_registration(surface)
    outcome = apply_unregistered_native_death_reports(
        conn,
        machine_id="machine-1",
        authorized_projects=[10],
        reports=[{"launch_id": launch.launch_id, "evidence": {"exit_code": 1}}],
        now="2026-08-22T12:00:45Z",
    )
    assert outcome["closed_launches"] == [launch.launch_id]
    recovery = _recovery(conn, launch.launch_id)
    assert recovery.endswith(SIGN_IN[surface])
    assert _manifest(surface).sign_in_recovery() in recovery
    assert "may be signed out" in recovery


@pytest.mark.parametrize("surface", sorted(SIGN_IN))
def test_registration_deadline_names_the_harness_sign_in(surface):
    conn, launch = _awaiting_registration(surface)
    changed = settle_launch_deadlines(conn, now="2026-08-22T12:11:00Z")
    assert [record.result_code for record in changed] == ["registration_deadline"]
    recovery = _recovery(conn, launch.launch_id)
    assert recovery.endswith(SIGN_IN[surface])
    assert _manifest(surface).sign_in_recovery() in recovery
    assert "may be signed out" in recovery
