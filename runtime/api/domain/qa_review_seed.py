"""Seed one blocking QA case whose agent-judged run came back undetermined.

Both the review-resolution tests and the review-trigger tests need the same
starting point — a blocking inspection requirement, a run that returned no
verdict, and role holders who may answer — so the shape lives in one place
rather than being re-authored per file.
"""

from __future__ import annotations

from runtime.api.fixtures.actor_roles import seed_project_role

from yoke_core.domain.decision_request_schema import (
    create_decision_request_tables,
)
from yoke_core.domain.qa_catalog_schema import (
    create_qa_catalog_tables,
    seed_builtin_qa_methods,
)


def _seed_undetermined_review(
    test_db,
    *,
    item_id,
    plan_slug,
    decider_roles,
    performed_by="agent",
    raw_result=None,
    case_outcome=None,
    execution_status=None,
):
    """Seed one blocking plan case whose agent run came back undetermined.

    Returns the seeded identities, including one distinct role-holding actor
    per entry in *decider_roles* so a caller can exercise a policy that needs
    more than one person.
    """
    create_decision_request_tables(test_db)
    create_qa_catalog_tables(test_db)
    seed_builtin_qa_methods(test_db)
    originator = test_db.execute(
        "SELECT id FROM actors ORDER BY id LIMIT 1"
    ).fetchone()[0]
    deciders = []
    for offset, role_name in enumerate(decider_roles):
        role = test_db.execute(
            "INSERT INTO roles (id, name, description, created_at) "
            "VALUES (%s, %s, 'Seeded', '2026-07-26T00:00:00Z') "
            "ON CONFLICT(name) DO UPDATE SET description=EXCLUDED.description "
            "RETURNING id",
            (9400 + offset, role_name),
        ).fetchone()[0]
        actor = test_db.execute(
            "INSERT INTO actors (id, kind, created_at) "
            "VALUES (%s, 'human', '2026-07-26T00:00:00Z') "
            "ON CONFLICT (id) DO UPDATE SET kind='human' RETURNING id",
            (item_id * 10 + offset,),
        ).fetchone()[0]
        test_db.execute(
            "INSERT INTO actor_project_roles "
            "(actor_id, project_id, role_id, granted_at) "
            "VALUES (%s, 1, %s, '2026-07-26T00:00:00Z') "
            "ON CONFLICT DO NOTHING",
            (actor, role),
        )
        deciders.append(int(actor))
    owner = deciders[0]
    workflow = test_db.execute(
        "SELECT current_version_id FROM workflows WHERE id='issue'"
    ).fetchone()[0]
    test_db.execute(
        "INSERT INTO items "
        "(id, title, status, priority, created_at, updated_at, source, owner, "
        "project_id, project_sequence, workflow_id, workflow_version_id) "
        "VALUES (%s, 'Review QA evidence', 'implementing', 'medium', "
        "'2026-07-26T00:00:00Z', '2026-07-26T00:00:00Z', %s, %s, "
        "1, %s, 'issue', %s)",
        (item_id, str(originator), str(owner), item_id, workflow),
    )
    plan_id = test_db.execute(
        "INSERT INTO qa_plans "
        "(project_id, slug, name, created_at, updated_at) "
        "VALUES (1, %s, 'Review proof', "
        "'2026-07-26T00:00:00Z', '2026-07-26T00:00:00Z') "
        "RETURNING id",
        (plan_slug,),
    ).fetchone()[0]
    requirement_id = test_db.execute(
        "INSERT INTO qa_requirements "
        "(item_id, plan_id, plan_case_key, method_id, method_name, "
        "expected_outcome, runner_id, capability_requirements, verdict_path, qa_kind, "
        "qa_phase, blocking_mode, created_at) "
        "VALUES (%s, %s, 'checkout-flow', 'browser-inspection', "
        "'Browser inspection', 'The saved state is visible.', "
        "'browser_substrate', '[\"browser-control\"]', "
        "'agent', 'plan_case', 'verification', 'blocking', "
        "'2026-07-26T00:00:00Z') RETURNING id",
        (item_id, plan_id),
    ).fetchone()[0]
    run_id = test_db.execute(
        "INSERT INTO qa_runs "
        "(qa_requirement_id, performed_by, qa_kind, verdict, verdict_reason, "
        "started_at, completed_at, created_at, raw_result, case_outcome, execution_status) "
        "VALUES (%s, %s, 'manual_acceptance', "
        "'undetermined', 'The screenshot does not show the saved state.', "
        "'2026-07-26T00:00:00Z', "
        "'2026-07-26T00:00:00Z', '2026-07-26T00:00:00Z', %s, %s, %s) RETURNING id",
        (requirement_id, performed_by, raw_result, case_outcome, execution_status),
    ).fetchone()[0]
    artifact_id = test_db.execute(
        "INSERT INTO qa_artifacts "
        "(qa_run_id, artifact_type, artifact_handle, created_at) "
        "VALUES (%s, 'screenshot', %s, '2026-07-26T00:00:00Z') RETURNING id",
        (run_id, '{"backend":"local","path":"/tmp/review.png"}'),
    ).fetchone()[0]
    test_db.commit()
    return {
        "originator": int(originator),
        "deciders": deciders,
        "plan_id": int(plan_id),
        "requirement_id": int(requirement_id),
        "run_id": int(run_id),
        "artifact_id": int(artifact_id),
    }


def resolve_capture_review(
    conn, *, requirement_id, action, actor_id, note, reviewed_run_id
):
    """Exercise the resolved decision that authorizes a provisional judgment."""
    from yoke_core.domain.qa_review_requests import ensure_qa_review_request
    from yoke_core.domain.decision_request_resolution import resolve_decision_request

    conn.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,artifact_handle,created_at) VALUES(%s,'screenshot','image/png',%s,%s)",
        (
            reviewed_run_id,
            '{"backend":"local","path":"/tmp/review.png"}',
            "2026-09-17T00:00:00Z",
        ),
    )
    seed_project_role(conn, actor_id=actor_id, project_id=1, role_name="owner")
    request, _ = ensure_qa_review_request(
        conn,
        requirement_id=requirement_id,
        run_id=reviewed_run_id,
        originator_actor_id=actor_id,
    )
    return resolve_decision_request(
        conn, request["id"], actor_id=actor_id, action=action, note=note
    )
