# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from uuid import uuid4

import pytest

from yoke_contracts.session_control.capabilities import SESSION_SURFACE_CAPABILITIES

from yoke_core.domain.session_launch_execution import (
    claim_assigned_launch,
    report_launch_attempt,
)

from yoke_core.domain.session_launch_registration import (
    complete_launch_for_message,
    complete_launch_injection,
    prepare_launch_registration,
)

from yoke_core.domain.session_launch_registration_candidate import (
    reserve_launch_registration_candidate,
)

from yoke_core.domain.session_launch_store import get_launch

from yoke_core.domain.session_launch_types import SessionLaunchError

from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    relay_connection,
)


def registered_launch(conn, surface, key):
    launch = assigned_launch(conn, key=key, surface=surface)
    claim = claim_assigned_launch(
        conn,
        launch_id=launch.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now=NOW,
    )
    session = str(uuid4())
    conn.execute(
        "INSERT INTO harness_sessions (session_id,project_id,executor_surface,"
        "executor_version,machine_id,model,workspace,offered_at) "
        "VALUES (?,10,?,?,'machine-1','gpt-5','/project',?)",
        (session, surface, SESSION_SURFACE_CAPABILITIES[surface].minimum_version, NOW),
    )
    conn.commit()
    return launch, claim, session


def bind(conn, launch, claim, session):
    return prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=claim.attestation,
        session_id=session,
        now="2026-08-22T12:00:02Z",
    )
