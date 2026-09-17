"""Standalone item cases persist a canonical target before a runnable roster."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain.handlers import qa_requirement_create
from yoke_core.domain.qa_plan_execution_state import (
    QaPlanExecutionStateError,
    begin_plan_execution,
)
from yoke_core.domain.qa_requirement_config_update import apply_requirement_update
from yoke_core.domain.qa_requirement_pass_currency import has_current_passing_run
from yoke_core.domain.qa_workflow_binding_validation import item_transition_for_gate
from yoke_core.domain.workflow_gate_catalog import GATE_QA_VERIFICATION

PREVIEW_URL = "http://127.0.0.1:8931"
TRANSITION = "implemented"


def _request(item_id: int, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="qa.requirement.add",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload,
    )


def _bound_browser_payload(conn, item_id: int, **extra) -> dict:
    payload = {
        "method_id": "browser-inspection",
        "qa_phase": "verification",
        "instructions": "Inspect the preview surface.",
        "expected_outcome": "The preview is reachable.",
        "method_config": {
            "base_url": PREVIEW_URL,
            "steps": [
                {"action": "navigate", "route": "/"},
                {"action": "screenshot", "capture": True},
            ],
        },
        "workflow_transition_id": item_transition_for_gate(
            conn,
            item_id=item_id,
            gate_id=GATE_QA_VERIFICATION,
        ),
    }
    payload.update(extra)
    return payload


def _environment(conn, *, project_id: int, name: str, url: str | None = None) -> None:
    site = conn.execute(
        "INSERT INTO sites (project_id, name, created_at) "
        "VALUES (%s, %s, %s) RETURNING id",
        (int(project_id), f"site-{project_id}-{name}", "2026-09-17T00:00:00Z"),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO environments (site, project_id, name, url, settings, "
        "created_at) VALUES (%s, %s, %s, %s, %s, %s)",
        (
            int(site),
            int(project_id),
            name,
            url,
            json.dumps({"hosts": {"app": url}} if url else {}),
            "2026-09-17T00:00:00Z",
        ),
    )
    conn.commit()


def test_add_without_target_env_stays_an_unbound_draft() -> None:
    with test_database() as conn:
        insert_item(conn, id=6401, title="Draft browser case", status="implementing")
        conn.commit()
        outcome = qa_requirement_create.handle_qa_requirement_add(
            _request(6401, _bound_browser_payload(conn, 6401))
        )
        assert outcome.primary_success, outcome.error
        row = conn.execute(
            "SELECT target_env, execution_target_json, execution_target_digest "
            "FROM qa_requirements WHERE id=%s",
            (outcome.result_payload["requirement_id"],),
        ).fetchone()
        assert row["target_env"] is None
        assert row["execution_target_json"] is None
        assert row["execution_target_digest"] is None


def test_add_with_authorized_target_persists_canonical_snapshot() -> None:
    with test_database() as conn:
        insert_item(conn, id=6402, title="Bound browser case", status="implementing")
        _environment(conn, project_id=1, name="local", url=PREVIEW_URL)
        outcome = qa_requirement_create.handle_qa_requirement_add(
            _request(
                6402,
                _bound_browser_payload(conn, 6402, target_env="local"),
            )
        )
        assert outcome.primary_success, outcome.error
        row = conn.execute(
            "SELECT target_env, execution_target_json, execution_target_digest "
            "FROM qa_requirements WHERE id=%s",
            (outcome.result_payload["requirement_id"],),
        ).fetchone()
        assert row["target_env"] == "local"
        target = json.loads(str(row["execution_target_json"]))
        assert target["environment"] == {"name": "local"}
        assert target["endpoints"]["app_url"] == PREVIEW_URL
        assert row["execution_target_digest"]


def test_add_with_wrong_project_target_is_refused() -> None:
    with test_database() as conn:
        insert_item(conn, id=6403, title="Wrong project target", status="implementing")
        _environment(conn, project_id=2, name="ext-stage", url=PREVIEW_URL)
        outcome = qa_requirement_create.handle_qa_requirement_add(
            _request(
                6403,
                _bound_browser_payload(conn, 6403, target_env="ext-stage"),
            )
        )
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"
        assert "not project 1" in outcome.error.message


def test_unregistered_target_name_stays_deferred() -> None:
    with test_database() as conn:
        insert_item(conn, id=6404, title="Deferred label", status="implementing")
        conn.commit()
        outcome = qa_requirement_create.handle_qa_requirement_add(
            _request(
                6404,
                _bound_browser_payload(conn, 6404, target_env="stage"),
            )
        )
        assert outcome.primary_success, outcome.error
        row = conn.execute(
            "SELECT target_env, execution_target_json FROM qa_requirements "
            "WHERE id=%s",
            (outcome.result_payload["requirement_id"],),
        ).fetchone()
        assert row["target_env"] == "stage"
        assert row["execution_target_json"] is None


def test_begin_without_target_names_cli_bind_and_skill() -> None:
    with test_database() as conn:
        insert_item(
            conn,
            id=6405,
            title="Untargeted close-out",
            workflow_id="issue",
        )
        requirement = insert_qa_requirement(
            conn,
            item_id=6405,
            qa_kind="method_case",
            method_id="browser-inspection",
            method_name="Browser inspection",
            runner_id="browser_substrate",
            verdict_path="agent",
            capability_requirements=json.dumps(["browser-control"]),
            workflow_transition_id=TRANSITION,
            instructions="Inspect the preview.",
            expected_outcome="The preview is reachable.",
        )
        with pytest.raises(QaPlanExecutionStateError, match="requirement") as exc:
            begin_plan_execution(
                conn,
                item_id=6405,
                transition_id=TRANSITION,
                actor_id="7",
                session_id="standalone-begin",
            )
        message = str(exc.value)
        assert str(requirement["id"]) in message
        assert "yoke qa requirement update" in message
        assert "yoke qa case run" in message
        assert "/yoke advance" in message
        assert "not a CLI command" in message


def test_update_then_begin_uses_persisted_snapshot() -> None:
    with test_database() as conn:
        insert_item(
            conn,
            id=6406,
            title="Correct then execute",
            workflow_id="issue",
        )
        _environment(conn, project_id=1, name="local", url=PREVIEW_URL)
        requirement = insert_qa_requirement(
            conn,
            item_id=6406,
            qa_kind="method_case",
            method_id="browser-inspection",
            method_name="Browser inspection",
            runner_id="browser_substrate",
            verdict_path="agent",
            capability_requirements=json.dumps(["browser-control"]),
            workflow_transition_id=TRANSITION,
            instructions="Inspect the preview.",
            expected_outcome="The preview is reachable.",
            method_config=json.dumps(
                {
                    "base_url": PREVIEW_URL,
                    "steps": [
                        {"action": "navigate", "route": "/"},
                        {"action": "screenshot", "capture": True},
                    ],
                }
            ),
        )
        conn.execute(
            "INSERT INTO qa_runs (qa_requirement_id, performed_by, qa_kind, "
            "verdict, raw_result, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                int(requirement["id"]),
                "browser_substrate",
                "method_case",
                "pass",
                "legacy capture",
                "2026-09-17T00:00:00Z",
            ),
        )
        conn.commit()
        assert has_current_passing_run(conn, int(requirement["id"]))
        result = apply_requirement_update(
            conn, int(requirement["id"]), "target_env", "local"
        )
        assert result.ok, result.message
        assert not has_current_passing_run(conn, int(requirement["id"]))
        execution = begin_plan_execution(
            conn,
            item_id=6406,
            transition_id=TRANSITION,
            actor_id="7",
            session_id="standalone-bound-begin",
        )
        assert execution["execution_target"]["environment"] == {"name": "local"}
        assert execution["execution_target_digest"]


def test_frozen_run_row_refuses_target_env_update() -> None:
    with test_database() as conn:
        insert_item(conn, id=6407, title="Frozen run case", status="implementing")
        requirement = insert_qa_requirement(
            conn,
            item_id=6407,
            qa_kind="method_case",
            method_id="browser-inspection",
            method_name="Browser inspection",
            runner_id="browser_substrate",
            verdict_path="agent",
            workflow_transition_id=TRANSITION,
            instructions="Inspect.",
            expected_outcome="Visible.",
        )
        conn.execute(
            "UPDATE qa_requirements SET item_id=NULL, deployment_run_id=%s "
            "WHERE id=%s",
            ("run-20260917-001", int(requirement["id"])),
        )
        conn.commit()
        result = apply_requirement_update(
            conn, int(requirement["id"]), "target_env", "local"
        )
        assert not result.ok
        assert result.error_code == "frozen_requirement_immutable"

