"""Machine-scoped sessions retain delivery and lifecycle authority."""

from datetime import timedelta

import pytest

from runtime.api.domain.test_session_registration_scope import register, world as world
from yoke_contracts.timestamps import utc_now
from yoke_core.domain import sessions_cleanup as cleanup
from yoke_core.domain.scratch_auto_prune import ScratchPruneResult
from yoke_core.domain.sessions_render_end_if_empty import end_session_if_empty


def _message(w, *, last_wake=None, message_id="delivery"):
    now = utc_now()
    w.conn.execute(
        "INSERT INTO session_messages(message_id,sender_actor_id,body,body_sha256,"
        "selector_snapshot,created_at,expires_at) VALUES "
        "(%s,%s,'work','digest','{}',%s,%s)",
        (message_id, w.owner, now, now + timedelta(hours=1)),
    )
    w.conn.execute(
        "INSERT INTO session_message_recipients(message_id,session_id,org_id,"
        "resolution_evidence,routing_snapshot,created_at,wake_after,last_wake_at) "
        "VALUES (%s,'registration',%s,'{}','{}',%s,%s,%s)",
        (message_id, w.org, now, now, last_wake),
    )
    w.conn.commit()


def _stale(w, monkeypatch):
    register(w)
    old = utc_now() - timedelta(days=7)
    w.conn.execute(
        "UPDATE harness_sessions SET offered_at=%s,last_heartbeat=%s,"
        "last_tool_call_at=%s,episode_started_at=%s WHERE session_id='registration'",
        (old, old, old, old),
    )
    w.conn.commit()
    monkeypatch.setattr(
        cleanup, "auto_prune_stale_scratch", lambda conn: ScratchPruneResult()
    )


def test_project_filtered_cleanup_skips_org_rows(world, monkeypatch):
    _stale(world, monkeypatch)
    result = cleanup.clean_stale_harness_sessions(world.conn, project_ids=[1])
    assert result["total_reclaimed"] == result["org_scoped_reclaimed"] == 0
    assert (
        world.conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id='registration'"
        ).fetchone()[0]
        is None
    )


def test_universe_cleanup_reaps_org_rows_releases_holds(world, monkeypatch):
    from runtime.api.domain.steering_claim_test_support import seed_strategy_doc
    from yoke_core.domain.strategy_doc_session_claims import acquire_session_doc_claim

    _stale(world, monkeypatch)
    seed_strategy_doc(world.conn, 1, "LIFECYCLE-PLAN")
    acquire_session_doc_claim(
        world.conn,
        project_id=1,
        slug="LIFECYCLE-PLAN",
        session_id="registration",
        actor_id=world.owner,
    )
    _message(world)
    result = cleanup.clean_stale_harness_sessions(world.conn)
    assert result["total_reclaimed"] == result["org_scoped_reclaimed"] == 1
    assert (
        world.conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id='registration'"
        ).fetchone()[0]
        is not None
    )
    assert (
        world.conn.execute(
            "SELECT released_at FROM strategy_doc_claims "
            "WHERE owner_session_id='registration'"
        ).fetchone()[0]
        is not None
    )
    assert (
        world.conn.execute(
            "SELECT state FROM session_message_recipients WHERE message_id='delivery'"
        ).fetchone()[0]
        == "cancelled"
    )


def test_cleanup_preserves_delivery_after_reclaim_reactivation(world, monkeypatch):
    _stale(world, monkeypatch)
    _message(world)
    original = cleanup.reclaim_stale_session

    def reactivate_after_commit(conn, session_id):
        result = original(conn, session_id)
        assert (
            conn.execute(
                "SELECT ended_at FROM harness_sessions WHERE session_id=%s",
                (session_id,),
            ).fetchone()[0]
            is not None
        )
        assert (
            conn.execute(
                "SELECT state FROM session_message_recipients WHERE message_id='delivery'"
            ).fetchone()[0]
            == "cancelled"
        )
        register(world)
        _message(world, message_id="fresh-delivery")
        return result

    monkeypatch.setattr(cleanup, "reclaim_stale_session", reactivate_after_commit)
    assert cleanup.clean_stale_harness_sessions(world.conn)["total_reclaimed"] == 1
    assert (
        world.conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id='registration'"
        ).fetchone()[0]
        is None
    )
    receipts = dict(
        world.conn.execute(
            "SELECT message_id,state FROM session_message_recipients "
            "WHERE session_id='registration'"
        ).fetchall()
    )
    assert receipts == {"delivery": "cancelled", "fresh-delivery": "pending"}


@pytest.mark.parametrize("wake", [False, True])
def test_end_if_empty_blocked_by_pending_and_holds(world, wake):
    register(world)
    _message(world, last_wake=utc_now() if wake else None)
    result = end_session_if_empty(world.conn, "registration")
    assert not result["ended"]
    assert result["status"] == (
        "wake_delivery_in_flight" if wake else "has_pending_messages"
    )


def test_concurrent_reap_and_hook_no_premature_end(world, monkeypatch):
    from runtime.api.fixtures.session_holdings import insert_steering_claim

    _stale(world, monkeypatch)
    original = cleanup.reclaim_facts

    def acquired_before_recheck(conn, rows):
        insert_steering_claim(conn, "registration", project_id=1)
        return original(conn, rows)

    monkeypatch.setattr(cleanup, "reclaim_facts", acquired_before_recheck)
    assert cleanup.clean_stale_harness_sessions(world.conn)["total_reclaimed"] == 0
    assert not end_session_if_empty(world.conn, "registration")["ended"]


def test_org_session_ends_after_expired_wake_grace(world):
    register(world)
    _message(world, last_wake=utc_now() - timedelta(seconds=301))
    assert end_session_if_empty(world.conn, "registration")["ended"]


def test_steer_multiple_projects_one_seat_each(world):
    from runtime.api.domain.steering_claim_test_support import seed_project
    from yoke_core.domain.steering_claims import acquire
    from yoke_core.domain.sessions_analytics import SessionError
    from yoke_core.domain.sessions_steering_visibility import steering_visibility

    register(world)
    register(world, sid="contender")
    seed_project(world.conn, 71, "lifecycle-second")
    for project in (1, 71):
        claim = acquire(world.conn, session_id="registration", project_id=project)
        assert claim["scope"] == {"project_id": project}
    with pytest.raises(SessionError, match="held"):
        acquire(world.conn, session_id="contender", project_id=1)
    rows = [{"session_id": "registration", "project_id": None, "org_id": world.org}]
    facts = steering_visibility(world.conn, rows)["registration"]
    assert facts["steering_group_session_id"] == "registration"
    assert facts["steering_scope"]["project_id"] in (1, 71)


def test_strategy_doc_lock_from_projectless(world):
    from runtime.api.domain.steering_claim_test_support import seed_strategy_doc
    from yoke_core.domain.strategy_doc_session_claims import acquire_session_doc_claim

    register(world)
    seed_strategy_doc(world.conn, 1, "ORG-PLAN")
    claim = acquire_session_doc_claim(
        world.conn,
        project_id=1,
        slug="ORG-PLAN",
        session_id="registration",
        actor_id=world.owner,
    )
    assert claim["project_id"] == 1 and claim["owner_session_id"] == "registration"
    assert (
        end_session_if_empty(world.conn, "registration")["status"]
        == "has_document_locks"
    )


def test_coordination_and_deploy_locks_from_projectless(world, monkeypatch):
    import json
    from yoke_core.domain import coordination_claims, db_optional_queries
    from yoke_core.domain.deployment_run_driver_attachment import DriverAttachment
    from yoke_core.domain.work_claim_targets import make_route_qualification_target

    _stale(world, monkeypatch)
    claim = coordination_claims.acquire(
        world.conn, make_route_qualification_target(1, "fixture-route"), "registration"
    )
    assert not end_session_if_empty(world.conn, "registration")["ended"]
    assert cleanup.clean_stale_harness_sessions(world.conn)["total_reclaimed"] == 0
    coordination_claims.release(world.conn, claim.id, reason="fixture completed")
    now = utc_now()
    driver = DriverAttachment(
        "fixture-run", "registration", 42, now, now, "executing", ""
    )
    original = db_optional_queries.fetch_optional_rows

    def driver_snapshot(conn, query, params, *, savepoint):
        if savepoint == "_yoke_idle_deployment_drivers":
            return [
                {
                    "id": "fixture-run",
                    "status": "executing",
                    "driver_attachment": json.dumps(driver.as_dict()),
                }
            ]
        return original(conn, query, params, savepoint=savepoint)

    monkeypatch.setattr(db_optional_queries, "fetch_optional_rows", driver_snapshot)
    assert (
        end_session_if_empty(world.conn, "registration")["status"]
        == "has_deployment_driver"
    )
    assert cleanup.clean_stale_harness_sessions(world.conn)["total_reclaimed"] == 0
    from dataclasses import replace

    driver = replace(driver, heartbeat_at=now - timedelta(hours=1))
    assert end_session_if_empty(world.conn, "registration")["ended"]


@pytest.mark.parametrize("target", [1, 81])
def test_inaccessible_target_refused_no_disclosure(world, target):
    from runtime.api.domain.test_function_authz_scope_routing import (
        _entry,
        _payload_request,
    )
    from yoke_core.domain.yoke_function_permissions import check_dispatch_permission
    from yoke_contracts.api.function_call import TargetRef

    register(world, actor_id=world.owner)
    if target == 81:
        world.conn.execute(
            "INSERT INTO organizations(id,slug,name,created_at) "
            "VALUES (81,'private-org','Private organization',%s)",
            (utc_now(),),
        )
        world.conn.execute(
            "INSERT INTO projects(id,slug,name,org_id,created_at) "
            "VALUES (81,'private-project','Private project',81,%s)",
            (utc_now(),),
        )
    actor = world.stranger if target == 1 else world.owner
    request = _payload_request(actor, "claims.steering.acquire", {}).model_copy(
        update={"target": TargetRef(kind="global", project_id=str(target))}
    )
    result = check_dispatch_permission(world.conn, _entry(request.function), request)
    assert result.error is not None
    assert result.error.error.code == "permission_denied"
    response = result.error.model_dump_json()
    assert result.error.result == {}
    assert "private-project" not in response
    assert "Private project" not in response
    assert "Private organization" not in response


def test_readable_target_keeps_permission_denial_teaching(world):
    from runtime.api.domain.test_function_authz_scope_routing import (
        _entry,
        _payload_request,
    )
    from yoke_core.domain.actor_permissions import grant_actor_project_role
    from yoke_core.domain.yoke_function_permissions import check_dispatch_permission
    from yoke_contracts.api.function_call import TargetRef

    grant_actor_project_role(
        world.conn, actor_id=world.stranger, project_id=1, role_name="viewer"
    )
    request = _payload_request(
        world.stranger, "claims.steering.acquire", {}
    ).model_copy(update={"target": TargetRef(kind="global", project_id="1")})
    result = check_dispatch_permission(world.conn, _entry(request.function), request)
    assert result.error is not None and result.project_id == 1
    assert result.project_slug == "yoke"
    assert "claims.acquire" in result.error.error.message
    assert "yoke" in result.error.error.message


def test_group_visibility_uses_session_authority_and_role_recipient_target(world):
    from yoke_core.domain.steering_claims import acquire
    from yoke_core.domain.sessions_steering_groups_read import (
        live_steering_group_session_ids,
    )
    from yoke_core.domain.steering_recipient_projection import steering_recipient

    register(world)
    acquire(world.conn, session_id="registration", project_id=1)
    assert live_steering_group_session_ids(
        world.conn, actor_id=world.owner, visible_project_ids={1}
    ) == ["registration"]
    assert (
        live_steering_group_session_ids(
            world.conn, actor_id=world.stranger, visible_project_ids={1}
        )
        == []
    )
    recipient = steering_recipient(
        world.conn,
        state="delivered",
        scope={"project_id": 1},
        project_id=1,
        sender_item_id=None,
        seat_session_id="registration",
    )
    assert recipient["project_id"] == 1
    assert recipient["session_id"] == "registration"
