"""Rebind accepts a snapshot whose endpoints already match the live host.

Identity labels can be stale or incoherent — a site name copied from
another environment, a missing environment id — while the URLs the case
actually hit already belong to the resolved environment. That is the
measured live-item dead end: every other recovery named a locked door,
and rebind refused on the labels. Host-authority refusal stays exact.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.test_qa_requirement_target_rebind import (
    _hosted_prod_pair,
    _stamp_requirement,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_execution_environment_target import (
    resolve_plan_execution_target,
)
from yoke_core.domain.qa_plan_management import QaPlanError, create_plan
from yoke_core.domain.qa_plan_requirement_snapshot import require_existing_target
from yoke_core.domain.qa_requirement_pass_currency import has_current_passing_run
from yoke_core.domain.qa_requirement_rebind_endpoint_delta import (
    exercised_endpoints_match,
    stale_label_rebind_applies,
)
from yoke_core.domain.qa_requirement_target_rebind import (
    QaRebindError,
    rebind_requirement,
)


def _stale_site_copy(live: dict, *, site: str) -> dict:
    stored = dict(live)
    stored["site"] = {"name": site}
    environment = dict(stored.get("environment") or {})
    environment.pop("id", None)
    stored["environment"] = environment
    stored["endpoints"] = dict(stored.get("endpoints") or {})
    return stored


def test_exercised_endpoints_match_ignores_stale_site_labels() -> None:
    stored = {
        "site": {"name": "Yoke API"},
        "endpoints": {"app_url": "https://app.upyoke.com"},
    }
    live = {
        "site": {"name": "yoke"},
        "endpoints": {"app_url": "https://app.upyoke.com"},
    }
    assert exercised_endpoints_match(stored, live)
    live_moved = {
        "site": {"name": "yoke"},
        "endpoints": {"app_url": "https://other.example.test"},
    }
    assert not exercised_endpoints_match(stored, live_moved)
    assert not exercised_endpoints_match(stored, {"site": {"name": "yoke"}})
    assert stale_label_rebind_applies(stored, live)
    named = {"environment": {"id": 3}, **stored}
    assert not stale_label_rebind_applies(named, live)


def test_rebind_rewrites_stale_site_when_endpoints_already_match() -> None:
    with test_database() as conn:
        hosted_id, _ = _hosted_prod_pair(conn)
        plan = create_plan(
            conn,
            project="yoke",
            slug="stale-label-rebind",
            target_environment="Yoke API/prod",
        )
        live = resolve_plan_execution_target(
            conn, plan_id=int(plan["id"]), require_runtime_match=False
        )
        assert live is not None
        stored = _stale_site_copy(live, site="yoke")
        requirement_id = _stamp_requirement(
            conn,
            item_id=9110,
            environment_id=hosted_id,
            plan_id=int(plan["id"]),
            target=stored,
        )
        row = conn.execute(
            "SELECT id, execution_target_json, execution_target_digest "
            "FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        ).fetchone()
        with pytest.raises(QaPlanError, match="rebind-target") as refusal:
            require_existing_target(
                [row],
                execution_target=live,
                subject="item 9110 transition implemented",
                conn=conn,
            )
        assert "supersede" not in str(refusal.value)

        result = rebind_requirement(
            conn,
            requirement_id=requirement_id,
            rationale="endpoints already match the resolved hosted prod target",
            actor_id=2,
        )
        assert result["already_current"] is False
        assert result["endpoint_delta"]["authority_changed"] == []
        rebound = json.loads(
            conn.execute(
                "SELECT execution_target_json FROM qa_requirements WHERE id=%s",
                (requirement_id,),
            ).fetchone()[0]
        )
        assert rebound["site"]["name"] == "Yoke API"
        assert has_current_passing_run(conn, requirement_id)
        current = conn.execute(
            "SELECT id, execution_target_json, execution_target_digest "
            "FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        ).fetchone()
        assert require_existing_target(
            [current],
            execution_target=live,
            subject="item 9110 transition implemented",
            conn=conn,
        ) == [requirement_id]


def test_rebind_still_refuses_stale_labels_when_host_moved() -> None:
    with test_database() as conn:
        hosted_id, _ = _hosted_prod_pair(conn)
        plan = create_plan(
            conn,
            project="yoke",
            slug="stale-label-host-moved",
            target_environment="Yoke API/prod",
        )
        live = resolve_plan_execution_target(
            conn, plan_id=int(plan["id"]), require_runtime_match=False
        )
        assert live is not None
        stored = _stale_site_copy(live, site="yoke")
        stored["endpoints"]["app_url"] = "https://other.example.test"
        requirement_id = _stamp_requirement(
            conn,
            item_id=9111,
            environment_id=hosted_id,
            plan_id=int(plan["id"]),
            target=stored,
        )
        with pytest.raises(QaRebindError) as exc:
            rebind_requirement(
                conn,
                requirement_id=requirement_id,
                rationale="should not follow a different host",
            )
        message = str(exc.value)
        assert "supersede" not in message
        assert "host authority" in message or "not the same environment identity" in message
