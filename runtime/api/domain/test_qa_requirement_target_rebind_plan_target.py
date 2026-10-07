"""Rebind resolves the plan target, not the plan project environment of the same name."""

from __future__ import annotations

import json

from yoke_core.domain.qa_execution_environment_target import (
    resolve_plan_execution_target,
)
from yoke_core.domain.qa_plan_management import create_plan
from yoke_core.domain.qa_requirement_target_rebind import (
    rebind_requirement,
)

from runtime.api.domain.test_qa_requirement_target_rebind import (
    _hosted_prod_pair,
    _stamp_requirement,
)
from runtime.api.fixtures.pg_testdb import test_database


def test_rebind_uses_plan_target_not_plan_project_environment_name() -> None:
    with test_database() as conn:
        hosted_id, _ = _hosted_prod_pair(conn)
        plan = create_plan(
            conn,
            project="yoke",
            slug="hosted-prod-rebind",
            target_environment="Yoke API/prod",
        )
        live = resolve_plan_execution_target(
            conn, plan_id=int(plan["id"]), require_runtime_match=False
        )
        stored = dict(live)
        stored["endpoints"] = dict(stored.get("endpoints") or {})
        stored["endpoints"]["app_url"] = "https://app.upyoke.com"
        stored["environment"] = {
            k: v for k, v in stored["environment"].items() if k != "id"
        }
        requirement_id = _stamp_requirement(
            conn,
            item_id=9107,
            environment_id=hosted_id,
            plan_id=int(plan["id"]),
            target=stored,
        )
        result = rebind_requirement(
            conn,
            requirement_id=requirement_id,
            rationale="scheme-only correction of the hosted prod target",
            actor_id=2,
        )
        assert result["already_current"] is False
        assert result["endpoint_delta"]["authority_changed"] == []
        kinds = {row["kind"] for row in result["endpoint_delta"]["changed"]}
        assert "scheme" in kinds
        rebound = json.loads(
            conn.execute(
                "SELECT execution_target_json FROM qa_requirements WHERE id=%s",
                (requirement_id,),
            ).fetchone()[0]
        )
        assert rebound["site"]["name"] == "Yoke API"
        assert rebound["endpoints"]["app_url"] == "http://app.upyoke.com"
