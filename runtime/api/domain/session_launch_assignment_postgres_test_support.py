# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from copy import deepcopy

import psycopg

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item

from yoke_core.domain import session_launch_requests

from yoke_core.domain.builtin_workflow_definitions import builtin_workflow_definition

from yoke_core.domain.item_ref_resolution import resolve_item_ref

from yoke_core.domain.project_identity import render_item_ref

from yoke_core.domain.session_launch_assignment import refuse_held_assigned_item

from yoke_core.domain.session_launch_delivery_state import IN_FLIGHT_LAUNCH_STATES

from yoke_core.domain.session_launch_types import (
    EligibleRelay,
    LaunchAuthorization,
    LaunchPreview,
    LaunchRequest,
    SessionLaunchError,
)

from yoke_core.domain.work_claim_targets import make_item_target

from yoke_core.domain.workflow_level_handoff import released_level_predecessor

from yoke_core.domain.workflow_registry import (
    converge_builtin_workflows,
    publish_workflow_version,
)

_NOW = "2026-10-08T12:00:00Z"


@pytest.fixture
def admission(test_db):
    assert isinstance(test_db, psycopg.Connection)
    converge_builtin_workflows(test_db)
    definition = deepcopy(builtin_workflow_definition("dash")["definition"])
    for stage in definition["stages"]:
        if stage["id"] == "release":
            stage["level"] = "JUNIOR"
    publish_workflow_version(test_db, workflow_id="dash", definition=definition)
    item = insert_item(
        test_db, project="admission-project", workflow_id="dash", status="release"
    )
    test_db.execute(
        "UPDATE projects SET public_item_prefix='ADMIT' WHERE id=%s",
        (item["project_id"],),
    )
    assert (
        resolve_item_ref(test_db, render_item_ref(test_db, item["id"], required=True))
        == item["id"]
    )
    actor_id = test_db.execute(
        "SELECT id FROM actors WHERE kind='human' ORDER BY id LIMIT 1"
    ).fetchone()[0]
    return test_db, item, int(actor_id)


def _session(context, name):
    conn, item, _actor = context
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, project_id, executor, provider, workspace, execution_level, "
        "offered_at, last_heartbeat) VALUES (%s,%s,'codex','openai',%s,'SENIOR',%s,%s)",
        (name, item["project_id"], "/checkouts/admission-project", _NOW, _NOW),
    )


def _claim(context, session, *, released=True, item_id=None):
    conn, item, _actor = context
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id,target_kind,scope,claim_type,claimed_at,last_heartbeat,released_at) "
        "VALUES (%s,'item',%s,'exclusive',%s,%s,%s)",
        (
            session,
            make_item_target(item_id or item["id"]).scope_json(),
            _NOW,
            _NOW,
            _NOW if released else None,
        ),
    )


def _launch(context, name, *, session=None, state="succeeded", native=False):
    conn, item, actor = context
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id,sender_actor_id,body,body_sha256,selector_snapshot,created_at,expires_at) "
        "VALUES (%s,%s,'Resume','fixture','{}',%s,%s)",
        (name, actor, _NOW, _NOW),
    )
    conn.execute(
        "INSERT INTO session_launches "
        "(launch_id,requester_actor_id,project_id,message_id,item_id,state,"
        "registered_session_id,native_session_id,deadline_at,created_at,"
        "requested_surface,selected_surface) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'codex-cli','codex-cli')",
        (
            name,
            actor,
            item["project_id"],
            name,
            item["id"],
            state,
            None if native else session,
            session if native else None,
            _NOW,
            _NOW,
        ),
    )
