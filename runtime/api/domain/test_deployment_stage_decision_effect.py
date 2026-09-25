"""An answered deployment stage decision reaches its run.

A resolved decision must change the run: an approved ready run can finish,
while a rejection closes it. These cover both answers, the stage nobody has
answered yet, and — because a recovery nobody can perform is not a recovery —
that the commands the wake carries are ones the CLI actually serves.
"""

from __future__ import annotations

from typing import Any

from runtime.api.deployment_stage_approval_fixture import seed_gate_run
from runtime.api.domain.coordination_claim_test_support import (
    PROJECT_YOKE,
    deploy_target,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    _bodies,
    _claim,
    _project,
    _recipients,
    seed_session,
)
from yoke_core.domain.decision_request_resolution import resolve_decision_request
from yoke_core.domain.decision_request_schema import create_decision_request_tables
from yoke_core.domain.deployment_approval_requests import (
    evaluate_deployment_stage_approval,
)
from yoke_core.domain.deployment_stage_decision_effect import (
    drive_recipe,
    stage_decision_idempotency_key,
)

DRIVER_SESSION = "sess-stage-driver"
STEERING_SESSION = "sess-stage-steering"
STAGE = "approve-prod"
ROLE_GATE_STAGES = (
    '[{"name":"approve-prod","step_runner":"human-approval",'
    '"approvals":{"roles":["owner"],"actors":[]}},'
    '{"name":"release","step_runner":"auto"}]'
)


def _owner_with_role(conn: Any) -> int:
    """An actor the gate's declared ``owner`` role authorizes to answer."""
    owner = int(
        conn.execute(
            "SELECT id FROM actors WHERE kind='human' ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    )
    role = int(
        conn.execute(
            "INSERT INTO roles (id, name, description, created_at) "
            "VALUES (9701, 'owner', 'Owner', '2026-07-26T00:00:00Z') "
            "ON CONFLICT(name) DO UPDATE SET description=EXCLUDED.description "
            "RETURNING id"
        ).fetchone()[0]
    )
    conn.execute(
        "INSERT INTO actor_project_roles (actor_id, project_id, role_id, granted_at) "
        "VALUES (%s, 1, %s, '2026-07-26T00:00:00Z') ON CONFLICT DO NOTHING",
        (owner, role),
    )
    conn.commit()
    return owner


def _pending_request(conn: Any, run_id: str) -> int:
    """The stage's own pending decision request, raised the way the gate does."""
    verdict = evaluate_deployment_stage_approval(conn, run_id=run_id, stage=STAGE)
    assert verdict.request_status == "pending"
    return int(verdict.request_id)


def _run_row(conn: Any, run_id: str) -> tuple[str, str, Any]:
    row = conn.execute(
        "SELECT status, COALESCE(current_stage, '') AS current_stage, completed_at "
        "FROM deployment_runs WHERE id = %s",
        (run_id,),
    ).fetchone()
    return str(row["status"]), str(row["current_stage"]), row["completed_at"]


def _seat(conn: Any, session_id: str, *, driver: bool) -> None:
    seed_session(conn, session_id)
    if driver:
        target = deploy_target(PROJECT_YOKE, "yoke")
        _claim(
            conn,
            session_id=session_id,
            target_kind=target.kind,
            scope_json=target.scope_json(),
        )
        return
    _claim(
        conn,
        session_id=session_id,
        target_kind="steering",
        scope_json='{"project_id": %d}' % PROJECT_YOKE,
    )


def test_a_resolved_approve_finishes_a_ready_run_without_waking_the_driver(
    test_db: Any,
) -> None:
    """The held deploy lock lets the answered final gate finish the run."""
    create_decision_request_tables(test_db)
    _project(test_db)
    owner = _owner_with_role(test_db)
    run_id = "run-stage-approved"
    seed_gate_run(
        test_db,
        flow_id="stage-approved",
        run_id=run_id,
        stages_json=ROLE_GATE_STAGES,
    )
    _seat(test_db, DRIVER_SESSION, driver=True)
    request_id = _pending_request(test_db, run_id)

    resolve_decision_request(
        test_db,
        request_id,
        actor_id=owner,
        action="approve",
        session_id="deciding-session",
    )

    status, stage, completed_at = _run_row(test_db, run_id)
    assert (status, stage) == ("succeeded", "complete")
    assert completed_at
    key = stage_decision_idempotency_key(run_id, STAGE, request_id, "approve")
    assert _recipients(test_db, key) == []


def test_a_resolved_reject_closes_the_run_instead_of_leaving_it_executing(
    test_db: Any,
) -> None:
    """A rejected stage has nothing left to advance, so the run cannot stay open."""
    create_decision_request_tables(test_db)
    _project(test_db)
    owner = _owner_with_role(test_db)
    run_id = "run-stage-rejected"
    seed_gate_run(
        test_db,
        flow_id="stage-rejected",
        run_id=run_id,
        stages_json=ROLE_GATE_STAGES,
    )
    _seat(test_db, DRIVER_SESSION, driver=True)
    request_id = _pending_request(test_db, run_id)

    resolve_decision_request(
        test_db,
        request_id,
        actor_id=owner,
        action="reject",
        session_id="deciding-session",
        note="not shipping this",
    )

    status, _stage, completed_at = _run_row(test_db, run_id)
    assert status == "failed"
    assert completed_at
    reason = test_db.execute(
        "SELECT envelope FROM events WHERE event_name = 'DeploymentRunTerminalized'"
    ).fetchone()
    assert reason is not None
    assert str(request_id) in str(reason["envelope"])
    # Nobody is woken: there is no run left to drive.
    assert (
        _recipients(
            test_db,
            stage_decision_idempotency_key(run_id, STAGE, request_id, "reject"),
        )
        == []
    )


def test_a_stage_nobody_has_answered_is_left_alone(test_db: Any) -> None:
    """Raising the request is not answering it, and must move nothing."""
    create_decision_request_tables(test_db)
    _project(test_db)
    _owner_with_role(test_db)
    run_id = "run-stage-unanswered"
    seed_gate_run(
        test_db,
        flow_id="stage-unanswered",
        run_id=run_id,
        stages_json=ROLE_GATE_STAGES,
    )
    _seat(test_db, DRIVER_SESSION, driver=True)
    request_id = _pending_request(test_db, run_id)

    assert _run_row(test_db, run_id)[:2] == ("executing", STAGE)
    assert (
        test_db.execute(
            "SELECT count(*) FROM session_messages WHERE idempotency_key LIKE %s",
            (f"deployment-stage-decision:{run_id}:%",),
        ).fetchone()[0]
        == 0
    )
    assert (
        str(
            test_db.execute(
                "SELECT status FROM decision_requests WHERE id = %s",
                (request_id,),
            ).fetchone()[0]
        )
        == "pending"
    )


def test_the_steering_seat_is_told_to_take_the_lock_the_executor_requires(
    test_db: Any,
) -> None:
    """The seat that answers in practice holds no lock, and executing needs one."""
    create_decision_request_tables(test_db)
    _project(test_db)
    owner = _owner_with_role(test_db)
    run_id = "run-stage-steering"
    seed_gate_run(
        test_db,
        flow_id="stage-steering",
        run_id=run_id,
        stages_json=ROLE_GATE_STAGES,
    )
    _seat(test_db, STEERING_SESSION, driver=False)
    request_id = _pending_request(test_db, run_id)

    resolve_decision_request(
        test_db,
        request_id,
        actor_id=owner,
        action="approve",
        session_id="deciding-session",
    )

    key = stage_decision_idempotency_key(run_id, STAGE, request_id, "approve")
    assert _recipients(test_db, key) == [STEERING_SESSION]
    [body] = _bodies(test_db, key)
    from yoke_core.domain.deploy_lock import acquire_command, release_command

    assert acquire_command("yoke") in body
    assert release_command("yoke") in body


def test_every_command_the_recipe_carries_is_one_the_cli_serves() -> None:
    """A recipe naming a command nobody can run is not a recovery.

    Each line is resolved against the live CLI surfaces rather than compared
    to a literal: the registry for wrapped operations, and the watcher table
    for the tool-shaped driver. A rename on either side fails here instead of
    reaching a person as an unrunnable instruction.
    """
    from yoke_cli.commands.registry import resolve
    from yoke_cli.commands.watchers import TOOL_SHAPED_USAGE

    recipes = (
        drive_recipe("run-recipe-check", "yoke", holds_lock=True),
        drive_recipe("run-recipe-check", "yoke", holds_lock=False),
    )
    checked = 0
    for recipe in recipes:
        for line in recipe.splitlines():
            tokens = line.split()
            assert tokens[0] == "yoke"
            tokens = tokens[1:]
            if tokens[0] == "--env":
                tokens = tokens[2:]
            form = " ".join(["yoke", *tokens[:2]])
            if form in TOOL_SHAPED_USAGE:
                checked += 1
                continue
            # Raises KeyError on an unknown route, which is the failure.
            resolve(tokens)
            checked += 1
    assert checked == 4
