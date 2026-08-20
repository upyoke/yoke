"""QA evidence review requests drive the canonical verdict state."""

from __future__ import annotations

from yoke_core.domain.decision_request_resolution import (
    resolve_decision_request,
)
from yoke_core.domain.decision_request_schema import (
    create_decision_request_tables,
)
from yoke_core.domain.qa_review_requests import ensure_qa_review_request
from yoke_core.domain.qa_catalog_schema import (
    create_qa_catalog_tables,
    seed_builtin_qa_methods,
)


def test_inconclusive_review_request_resolves_to_human_verdict(test_db):
    create_decision_request_tables(test_db)
    create_qa_catalog_tables(test_db)
    seed_builtin_qa_methods(test_db)
    originator = test_db.execute(
        "SELECT id FROM actors ORDER BY id LIMIT 1"
    ).fetchone()[0]
    owner = test_db.execute(
        "SELECT id FROM actors ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    role = test_db.execute(
        "INSERT INTO roles (id, name, description, created_at) "
        "VALUES (9401, 'owner', 'Owner', '2026-07-26T00:00:00Z') "
        "ON CONFLICT(name) DO UPDATE SET description=EXCLUDED.description "
        "RETURNING id"
    ).fetchone()[0]
    workflow = test_db.execute(
        "SELECT current_version_id FROM workflows WHERE id='issue'"
    ).fetchone()[0]
    test_db.execute(
        "INSERT INTO items "
        "(id, title, status, priority, created_at, updated_at, source, owner, "
        "project_id, project_sequence, workflow_id, workflow_version_id) "
        "VALUES (9501, 'Review QA evidence', 'implementing', 'medium', "
        "'2026-07-26T00:00:00Z', '2026-07-26T00:00:00Z', %s, %s, "
        "1, 9501, 'issue', %s)",
        (str(originator), str(owner), workflow),
    )
    test_db.execute(
        "INSERT INTO actor_project_roles "
        "(actor_id, project_id, role_id, granted_at) "
        "VALUES (%s, %s, %s, '2026-07-26T00:00:00Z') "
        "ON CONFLICT DO NOTHING",
        (owner, 1, role),
    )
    plan_id = test_db.execute(
        "INSERT INTO qa_plans "
        "(project_id, slug, name, created_at, updated_at) "
        "VALUES (1, 'review-proof', 'Review proof', "
        "'2026-07-26T00:00:00Z', '2026-07-26T00:00:00Z') "
        "RETURNING id"
    ).fetchone()[0]
    requirement_id = test_db.execute(
        "INSERT INTO qa_requirements "
        "(item_id, plan_id, plan_case_key, method_id, method_name, "
        "runner_id, capability_requirements, verdict_path, qa_kind, "
        "qa_phase, blocking_mode, created_at) "
        "VALUES (%s, %s, 'checkout-flow', 'browser-inspection', "
        "'Browser inspection', 'browser_substrate', '[\"browser-control\"]', "
        "'agent', 'plan_case', 'verification', 'blocking', "
        "'2026-07-26T00:00:00Z') RETURNING id",
        (9501, plan_id),
    ).fetchone()[0]
    run_id = test_db.execute(
        "INSERT INTO qa_runs "
        "(qa_requirement_id, performed_by, qa_kind, verdict, "
        "started_at, completed_at, created_at) "
        "VALUES (%s, 'browser_substrate', 'manual_acceptance', "
        "'inconclusive', '2026-07-26T00:00:00Z', "
        "'2026-07-26T00:00:00Z', '2026-07-26T00:00:00Z') RETURNING id",
        (requirement_id,),
    ).fetchone()[0]
    test_db.commit()

    request, created = ensure_qa_review_request(
        test_db,
        requirement_id=int(requirement_id),
        run_id=int(run_id),
        originator_actor_id=int(originator),
    )
    assert created is True
    assert request is not None
    assert request["subject_context"] == {
        "requirement_id": int(requirement_id),
        "run_id": int(run_id),
        "plan_id": int(plan_id),
        "qa_kind": "plan_case",
        "plan_name": "Review proof",
        "case_name": "checkout-flow",
        "method_name": "Browser inspection",
        "title": "QA evidence needs your review",
        "evidence_summary": "",
    }
    resolve_decision_request(
        test_db,
        int(request["id"]),
        actor_id=int(owner),
        action="approve",
        note="Evidence demonstrates the expected behavior.",
    )
    verdicts = test_db.execute(
        "SELECT performed_by, verdict FROM qa_runs "
        "WHERE qa_requirement_id=%s ORDER BY id",
        (requirement_id,),
    ).fetchall()
    assert [(row[0], row[1]) for row in verdicts] == [
        ("browser_substrate", "inconclusive"),
        ("human_review", "pass"),
    ]
