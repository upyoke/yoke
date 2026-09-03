"""QA evidence review requests drive the canonical verdict state."""

from __future__ import annotations

from yoke_core.domain.approval_policy import ApprovalPolicy
from yoke_core.domain.decision_request_resolution import (
    resolve_decision_request,
)
from yoke_core.domain.decision_request_schema import (
    create_decision_request_tables,
)
from yoke_core.domain.qa_review_requests import (
    ensure_qa_review_request,
    requirement_awaits_human_review,
)
from yoke_core.domain.qa_catalog_schema import (
    create_qa_catalog_tables,
    seed_builtin_qa_methods,
)


def _seed_undetermined_review(test_db, *, item_id, plan_slug, decider_roles):
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
        "started_at, completed_at, created_at) "
        "VALUES (%s, 'agent', 'manual_acceptance', "
        "'undetermined', 'The screenshot does not show the saved state.', "
        "'2026-07-26T00:00:00Z', "
        "'2026-07-26T00:00:00Z', '2026-07-26T00:00:00Z') RETURNING id",
        (requirement_id,),
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


def test_undetermined_review_request_resolves_to_human_verdict(test_db):
    seeded = _seed_undetermined_review(
        test_db,
        item_id=9501,
        plan_slug="review-proof",
        decider_roles=("owner",),
    )
    originator = seeded["originator"]
    owner = seeded["deciders"][0]
    plan_id = seeded["plan_id"]
    requirement_id = seeded["requirement_id"]
    run_id = seeded["run_id"]
    artifact_id = seeded["artifact_id"]

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
        "expected_outcome": "The saved state is visible.",
        "verdict_reason": "The screenshot does not show the saved state.",
        "artifacts": [
            {
                "artifact_id": int(artifact_id),
                "artifact_type": "screenshot",
                "content_type": None,
            }
        ],
        "artifact_count": 1,
        "evidence_state": "attached",
        "evidence_summary": "1 attached artifact(s): screenshot",
    }
    waiting = requirement_awaits_human_review(test_db, int(requirement_id))
    assert waiting is not None
    assert waiting.request_id == int(request["id"])
    assert waiting.authorities == ("project operator", "project owner")
    assert "awaits human evidence review" in waiting.detail
    assert f"resolve {request['id']} approve|reject|waive" in waiting.recovery
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
        ("agent", "undetermined"),
        ("human_review", "pass"),
    ]
    assert requirement_awaits_human_review(test_db, int(requirement_id)) is None

    empty_run_id = test_db.execute(
        "INSERT INTO qa_runs "
        "(qa_requirement_id, performed_by, qa_kind, verdict, verdict_reason, "
        "started_at, completed_at, created_at) VALUES "
        "(%s, 'agent', 'manual_acceptance', 'undetermined', "
        "'The attempt ended before producing reviewable proof.', "
        "'2026-07-26T00:01:00Z', '2026-07-26T00:01:00Z', "
        "'2026-07-26T00:01:00Z') RETURNING id",
        (requirement_id,),
    ).fetchone()[0]
    empty_request, empty_created = ensure_qa_review_request(
        test_db,
        requirement_id=int(requirement_id),
        run_id=int(empty_run_id),
        originator_actor_id=int(originator),
    )
    assert empty_created is True
    assert empty_request is not None
    assert empty_request["subject_context"]["artifacts"] == []
    assert empty_request["subject_context"]["artifact_count"] == 0
    assert empty_request["subject_context"]["evidence_state"] == "missing"
    assert empty_request["subject_context"]["evidence_summary"] == (
        "No evidence artifacts are attached to this run."
    )


def test_all_mode_review_holds_the_qa_verdict_until_every_box_decides(test_db):
    seeded = _seed_undetermined_review(
        test_db,
        item_id=9502,
        plan_slug="review-proof-all",
        decider_roles=("owner", "operator"),
    )
    requirement_id = seeded["requirement_id"]
    first_decider, second_decider = seeded["deciders"]

    request, created = ensure_qa_review_request(
        test_db,
        requirement_id=requirement_id,
        run_id=seeded["run_id"],
        policy=ApprovalPolicy(roles=("operator", "owner"), mode="all"),
        originator_actor_id=seeded["originator"],
    )
    assert created is True
    assert request is not None

    partial = resolve_decision_request(
        test_db,
        int(request["id"]),
        actor_id=first_decider,
        action="approve",
        note="Owner reviewed the evidence.",
    )
    assert partial["status"] == "pending"
    assert partial["approval_progress"]["satisfied"] == 1
    assert partial["approval_progress"]["required"] == 2
    assert requirement_awaits_human_review(test_db, requirement_id) is not None
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_runs "
            "WHERE qa_requirement_id=%s AND performed_by='human_review'",
            (requirement_id,),
        ).fetchone()[0]
        == 0
    )

    finished = resolve_decision_request(
        test_db,
        int(request["id"]),
        actor_id=second_decider,
        action="approve",
        note="Operator reviewed the evidence.",
    )
    assert finished["status"] == "resolved"
    assert finished["resolution_action"] == "approve"
    assert (
        test_db.execute(
            "SELECT verdict FROM qa_runs "
            "WHERE qa_requirement_id=%s AND performed_by='human_review'",
            (requirement_id,),
        ).fetchone()[0]
        == "pass"
    )
    assert requirement_awaits_human_review(test_db, requirement_id) is None
