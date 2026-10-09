"""Item launch admission executes against PostgreSQL, including successor SQL."""

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
        "(launch_id,requester_actor_id,project_id,message_id,session_name,state,"
        "registered_session_id,native_session_id,deadline_at,created_at,"
        "requested_surface,selected_surface) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'codex-cli','codex-cli')",
        (
            name,
            actor,
            item["project_id"],
            name,
            f"{render_item_ref(conn, item['id'], required=True)}: Resume",
            state,
            None if native else session,
            session if native else None,
            _NOW,
            _NOW,
        ),
    )


def _admit(context, *, predecessor=None, level="JUNIOR"):
    conn, item, _actor = context
    refuse_held_assigned_item(
        conn,
        public_ref=render_item_ref(conn, item["id"], required=True),
        project_id=item["project_id"],
        predecessor_session_id=predecessor,
        successor_level=level,
    )


def _released_predecessor(context):
    _session(context, "predecessor")
    _claim(context, "predecessor")
    _launch(context, "predecessor-launch", session="predecessor")
    conn, item, _actor = context
    assert (
        released_level_predecessor(
            conn, item_id=item["id"], session_id="predecessor", level="JUNIOR"
        )
        == "predecessor"
    )


def _create(admission, monkeypatch, *, predecessor=None, level=None):
    conn, item, actor = admission
    relay = EligibleRelay("relay", "worker-machine", "codex-cli", "1", _NOW)
    monkeypatch.setattr(
        session_launch_requests,
        "preview_launch",
        lambda *_a, **_k: LaunchPreview("launchable", "codex-cli", (relay,), relay),
    )
    monkeypatch.setattr(
        session_launch_requests,
        "preview_level_launch",
        lambda *_a, request, **_k: (
            request,
            LaunchPreview("launchable", "codex-cli", (relay,), relay),
        ),
    )
    conn.commit()
    return session_launch_requests.create_launch(
        conn,
        auth=LaunchAuthorization(actor, predecessor, True),
        request=LaunchRequest(
            project_id=item["project_id"],
            executor_surface="codex-cli",
            instructions="Resume the item",
            item=render_item_ref(conn, item["id"], required=True),
            idempotency_key="ordinary",
            level=level,
        ),
        now=_NOW,
    )


def test_ordinary_create_without_predecessor_commits_launch(admission, monkeypatch):
    outcome = _create(admission, monkeypatch)
    conn, _item, _actor = admission
    assert outcome.launch.requester_session_id is None
    assert conn.execute("SELECT COUNT(*) FROM session_launches").fetchone()[0] == 1


def test_released_level_predecessor_admits_its_own_successor(admission, monkeypatch):
    _released_predecessor(admission)
    _admit(admission, predecessor="predecessor")
    outcome = _create(admission, monkeypatch, predecessor="predecessor", level="JUNIOR")
    assert outcome.launch.requested_level == "JUNIOR"
    assert outcome.launch.requester_session_id == "predecessor"
    assert (
        admission[0].execute("SELECT COUNT(*) FROM session_launches").fetchone()[0] == 2
    )


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("predecessor", [None, "predecessor"])
def test_unrelated_live_launch_still_blocks(admission, predecessor, native):
    if predecessor:
        _released_predecessor(admission)
    _session(admission, "unrelated")
    _launch(admission, "unrelated-launch", session="unrelated", native=native)
    with pytest.raises(SessionLaunchError) as failure:
        _admit(admission, predecessor=predecessor)
    assert failure.value.code == "item_has_live_worker"


@pytest.mark.parametrize("state", [*sorted(IN_FLIGHT_LAUNCH_STATES), "outcome_unknown"])
@pytest.mark.parametrize("predecessor", [None, "predecessor"])
def test_unregistered_inflight_or_unknown_launch_still_blocks(
    admission, predecessor, state
):
    if predecessor:
        _released_predecessor(admission)
    _launch(admission, "unsettled-launch", state=state)
    with pytest.raises(SessionLaunchError) as failure:
        _admit(admission, predecessor=predecessor)
    assert failure.value.code == "item_has_live_worker"


@pytest.mark.parametrize(
    "invalid", ["active_item_claim", "other_active_claim", "same_level", "not_latest"]
)
def test_unvalidated_predecessor_is_never_excluded(admission, invalid):
    _released_predecessor(admission)
    conn, _item, _actor = admission
    level = "JUNIOR"
    if invalid == "active_item_claim":
        conn.execute("UPDATE work_claims SET released_at=NULL")
    elif invalid == "other_active_claim":
        _claim(admission, "predecessor", released=False, item_id=2)
    elif invalid == "same_level":
        level = "SENIOR"
    else:
        _session(admission, "newer")
        _claim(admission, "newer")
    with pytest.raises(SessionLaunchError) as failure:
        _admit(admission, predecessor="predecessor", level=level)
    assert failure.value.code == "item_has_live_worker"


def test_live_claim_holder_blocks_without_any_launch(admission):
    _session(admission, "holder")
    _claim(admission, "holder", released=False)
    with pytest.raises(SessionLaunchError) as failure:
        _admit(admission)
    assert failure.value.code == "item_has_live_worker"
