# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from datetime import datetime, timedelta, timezone

import json

from types import SimpleNamespace

import pytest

from yoke_contracts.timestamps import format_instant

from yoke_core.domain.actors import seed_human_actor

from yoke_core.domain.external_identities import default_org_id

from yoke_core.domain import session_native_turn_end as turns

from yoke_core.domain import session_process_liveness_report as liveness

from yoke_core.domain import session_idle_host_report as idle

from yoke_core.domain import session_vendor_error_resume as resume

from yoke_core.domain.session_capacity_recovery import relaunch_capacity_worker

from yoke_core.domain.session_relay_machine_versions import (
    connected_relay_routes,
    machine_surface_versions,
)

from yoke_core.domain.session_vendor_error_states import vendor_error_states

from yoke_core.domain.session_recovery_facts import (
    record_native_turn_end,
    resume_episode_key,
)

from yoke_core.domain.handlers.session_keepalive import _authorized_target

from yoke_core.domain.session_keepalive import hold_session_keepalive

from yoke_core.domain.session_message_types import SessionMessageError

from runtime.api.domain.session_process_liveness_report_test_support import (
    MEASURED_USAGE,
)

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)

OLD = NOW - timedelta(hours=2)

MACHINE = "org-machine"


@pytest.fixture
def world(test_db):
    owner = seed_human_actor(test_db, "Session owner")
    foreign = seed_human_actor(test_db, "Foreign owner")
    org = default_org_id(test_db)
    for sid, actor, machine, project in (
        ("own", owner, MACHINE, None),
        ("foreign", foreign, MACHINE, None),
        ("remote", owner, "other-machine", None),
        ("project", foreign, MACHINE, 1),
    ):
        test_db.execute(
            "INSERT INTO harness_sessions (session_id,executor,executor_surface,provider,"
            "workspace,project_id,org_id,actor_id,machine_id,offered_at,last_heartbeat,"
            "last_tool_call_at,turn_posture) VALUES (%s,'codex','codex-cli','openai',"
            "'/tmp/relay-fixture',%s,%s,%s,%s,%s,%s,%s,'running')",
            (sid, project, None if project else org, actor, machine, OLD, OLD, OLD),
        )
    test_db.commit()
    return test_db, owner, foreign
