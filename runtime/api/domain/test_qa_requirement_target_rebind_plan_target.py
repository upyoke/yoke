"""Rebind resolves the requirement's own target, then the plan target.

Neither falls back to the plan project's environment of the same name.
"""

from __future__ import annotations

import json

from yoke_core.domain.qa_execution_environment_target import (
    resolve_plan_execution_target,
)
from yoke_core.domain.qa_plan_management import create_plan
from yoke_core.domain.qa_requirement_target_rebind import (
    rebind_requirement,
)

from runtime.api.domain.qa_requirement_target_rebind_test_support import (
    _hosted_prod_pair,
    _identity,
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


def test_rebind_resolves_requirement_target_env_before_plan_default() -> None:
    from yoke_core.domain.qa_environment_execution_target import (
        environment_execution_target,
    )

    with test_database() as conn:
        _hosted_prod_pair(conn)
        stage_settings = json.dumps(
            {
                "qa": {"hosted_runtime": True, "hosted_runtime_consumer": "yoke"},
                "hosts": {
                    "app": "http://app.stage.upyoke.com",
                    "api": "https://api.stage.upyoke.com",
                },
                "distribution": {
                    "base_url": "https://dist.example.test",
                    "channel": "stage",
                },
            }
        )
        stage_id = conn.execute(
            "INSERT INTO environments(site,project_id,name,settings,created_at) "
            "SELECT id,3,'stage',%s,'2026-01-01T00:00:00Z' FROM sites "
            "WHERE project_id=3 AND name='Yoke API' RETURNING id",
            (stage_settings,),
        ).fetchone()[0]
        conn.commit()
        plan = create_plan(
            conn,
            project="yoke",
            slug="hosted-two-target-rebind",
            target_environment="Yoke API/prod",
        )
        live = environment_execution_target(
            conn, _identity(conn, stage_id), require_runtime_match=False
        )
        stored = dict(live)
        stored["endpoints"] = dict(stored.get("endpoints") or {})
        stored["endpoints"]["app_url"] = "https://app.stage.upyoke.com"
        stored["environment"] = {
            k: v for k, v in stored["environment"].items() if k != "id"
        }
        requirement_id = _stamp_requirement(
            conn,
            item_id=9108,
            environment_id=stage_id,
            plan_id=int(plan["id"]),
            target=stored,
        )
        conn.execute(
            "UPDATE qa_requirements SET target_env='stage' WHERE id=%s",
            (requirement_id,),
        )
        conn.commit()
        result = rebind_requirement(
            conn,
            requirement_id=requirement_id,
            rationale="scheme-only correction of the hosted stage target",
            actor_id=2,
        )
        assert result["already_current"] is False
        rebound = json.loads(
            conn.execute(
                "SELECT execution_target_json FROM qa_requirements WHERE id=%s",
                (requirement_id,),
            ).fetchone()[0]
        )
        assert rebound["environment"]["name"] == "stage"
        assert rebound["endpoints"]["app_url"] == "http://app.stage.upyoke.com"
