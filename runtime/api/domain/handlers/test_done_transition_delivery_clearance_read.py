"""``done_transition.delivery_clearance``: one item's clearance, answered on
the server from that item's own project and nothing else."""

from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import patch

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.deploy_defaults import set_default_flow_on_connection
from yoke_core.domain.handlers.done_transition_delivery_clearance_read import (
    handle_delivery_clearance,
)
from yoke_core.domain.project_structure import create_project_structure_tables
from yoke_core.domain.workflow_project_defaults import _effective_delivery_flow

NOW = "2026-11-19T00:00:00Z"


def _flow(conn, flow_id: str, project_id: int, tier: str | None) -> None:
    env = (
        "(SELECT id FROM environments WHERE project_id=%s AND name='prod')"
        if tier
        else "NULL"
    )
    params = (flow_id, project_id, flow_id, NOW, tier) + ((project_id,) if tier else ())
    conn.execute(
        "INSERT INTO deployment_flows("
        "id, project_id, name, description, stages, on_failure, created_at, "
        "status, target_tier, target_environment_id"
        f") VALUES (%s, %s, %s, '', '[]', 'halt', %s, 'active', %s, {env})",
        params,
    )


def _item(conn, item_id: int, project_id: int) -> None:
    conn.execute(
        "INSERT INTO items (id, title, workflow_id, workflow_version_id, status, "
        "created_at, updated_at, project_id, project_sequence) VALUES (%s, %s, "
        "'dash', (SELECT current_version_id FROM workflows WHERE id='dash'), "
        "'idea', %s, %s, %s, %s)",
        (item_id, f"Item {item_id}", NOW, NOW, project_id, item_id),
    )


@pytest.fixture
def db(test_db):
    create_project_structure_tables(test_db)
    test_db.execute(
        "INSERT INTO projects (id, slug, name, public_item_prefix, created_at) "
        "VALUES (2, 'other', 'Other', 'OTH', %s) ON CONFLICT DO NOTHING",
        (NOW,),
    )
    test_db.execute(
        "INSERT INTO environments(site, project_id, name, created_at) "
        "SELECT id, 1, 'prod', %s FROM sites WHERE project_id=1 "
        "ORDER BY id LIMIT 1 ON CONFLICT(project_id,name) DO NOTHING",
        (NOW,),
    )
    _flow(test_db, "acme-prod", 1, "persistent")
    _flow(test_db, "acme-runless", 1, None)
    _flow(test_db, "other-runless", 2, None)
    _item(test_db, 9001, 1)
    test_db.commit()
    with patch(
        "yoke_core.domain.db_helpers.connect", return_value=nullcontext(test_db)
    ):
        yield test_db


def _ask(*, deploy_flow: str = "", workflow_id: str = "dash", item_id: int = 9001):
    outcome = handle_delivery_clearance(
        FunctionCallRequest(
            function="done_transition.delivery_clearance",
            actor=ActorContext(actor_id="2", session_id="s-clearance"),
            target=TargetRef(kind="item", item_id=item_id),
            payload={"workflow_id": workflow_id, "deploy_flow": deploy_flow},
        )
    )
    assert outcome.primary_success, outcome.error
    return outcome.result_payload


def test_no_flow_and_no_project_default_is_merge_only(db):
    assert _ask() == {"merge_only": True, "resolved_flow": "", "blocked_reason": ""}


def test_another_projects_default_never_reaches_this_item(db):
    other = db.execute("SELECT slug FROM projects WHERE id=2").fetchone()[0]
    assert set_default_flow_on_connection(db, other, "other-runless") is True
    db.commit()
    assert _ask() == {"merge_only": True, "resolved_flow": "", "blocked_reason": ""}


def test_project_default_with_a_null_target_tier_is_merge_only(db):
    set_default_flow_on_connection(db, "yoke", "acme-runless")
    db.commit()
    assert _ask() == {
        "merge_only": True, "resolved_flow": "acme-runless", "blocked_reason": "",
    }


def test_project_default_that_deploys_waits_on_release(db):
    set_default_flow_on_connection(db, "yoke", "acme-prod")
    db.commit()
    assert _ask() == {
        "merge_only": False, "resolved_flow": "acme-prod", "blocked_reason": "",
    }


def test_an_explicit_flow_skips_the_default(db):
    set_default_flow_on_connection(db, "yoke", "acme-prod")
    db.commit()
    assert _ask(deploy_flow="acme-runless")["merge_only"] is True


def test_an_unregistered_flow_is_blocked_with_todays_reason(db):
    assert _ask(deploy_flow="typo-flow") == {
        "merge_only": False,
        "resolved_flow": "typo-flow",
        "blocked_reason": "deployment_flow 'typo-flow' is not a registered deployment flow.",
    }


def test_the_response_carries_only_the_verdict(db):
    set_default_flow_on_connection(db, "yoke", "acme-prod")
    db.commit()
    assert set(_ask()) == {"merge_only", "resolved_flow", "blocked_reason"}


def test_an_unread_item_project_fails_closed(db):
    outcome = handle_delivery_clearance(
        FunctionCallRequest(
            function="done_transition.delivery_clearance",
            actor=ActorContext(actor_id="2", session_id="s-clearance"),
            target=TargetRef(kind="item", item_id=987654),
            payload={"workflow_id": "dash", "deploy_flow": ""},
        )
    )
    assert outcome.primary_success is False
    assert outcome.error.code == "delivery_clearance_failed"


def test_a_target_without_an_item_is_refused():
    outcome = handle_delivery_clearance(
        FunctionCallRequest(
            function="done_transition.delivery_clearance",
            actor=ActorContext(actor_id="2", session_id="s-clearance"),
            target=TargetRef(kind="item"),
            payload={},
        )
    )
    assert outcome.error.code == "target_invalid"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"deployment_flow": "proj", "workflow_defaults": {"dash": "wf"}}, "wf"),
        ({"deployment_flow": "proj", "workflow_defaults": {"issue": "wf"}}, "proj"),
        # An explicitly empty workflow choice does not fall back.
        ({"deployment_flow": "proj", "workflow_defaults": {"dash": ""}}, ""),
        ({}, ""),
    ],
)
def test_effective_default_keeps_the_mechanics_semantics(payload, expected):
    assert _effective_delivery_flow(payload, "dash") == expected
