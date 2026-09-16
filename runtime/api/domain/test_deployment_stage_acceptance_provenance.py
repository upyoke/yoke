"""What a stage acceptance review can tell the person asked to answer it.

An acceptance records an aggregate verdict and captures nothing of its own,
and its candidate belongs to the run rather than to its own result. Read from
those two records alone, the review said "No evidence attached, so a pass or
fail here would be a verdict on nothing" and "revision not recorded" — on a
page already showing the screenshots its cases captured, for a run whose
Identity card named the candidate. Both facts were recorded; neither was
being read from the record that held it.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.test_deployment_qa_run_acceptance import (
    _acceptance_requirement_id,
    _settle,
)
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from yoke_core.domain.qa_review_evidence import qa_review_artifact_context
from yoke_core.domain.qa_review_requirement_facts import requirement_facts


def _case_requirement_ids(conn: Any, run_id: str, member: int) -> list[int]:
    rows = conn.execute(
        "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_member_item_id=%s AND method_id IS NOT NULL ORDER BY id",
        (run_id, member),
    ).fetchall()
    return [int(row["id"]) for row in rows]


def _latest_run_id(conn: Any, requirement_id: int) -> int:
    row = conn.execute(
        "SELECT id FROM qa_runs WHERE qa_requirement_id=%s "
        "ORDER BY created_at DESC,id DESC LIMIT 1",
        (requirement_id,),
    ).fetchone()
    return int(row["id"])


def _attach(conn: Any, qa_run_id: int, handle: str) -> int:
    row = conn.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,"
        "artifact_handle,created_at) VALUES (%s,'screenshot','image/png',%s,%s) "
        "RETURNING id",
        (qa_run_id, handle, "2026-09-14T00:03:00Z"),
    ).fetchone()
    conn.commit()
    return int(row["id"])


def test_an_acceptance_shows_the_evidence_its_cases_captured(test_db) -> None:
    plan_id = _plan(test_db, "acceptance-evidence")
    _seed_run(
        test_db, run_id="run-evidence", stages=_stages(plan_id), members=(9920,)
    )
    _settle(test_db, run_id="run-evidence", stage="item-qa", member=9920)
    case_id = _case_requirement_ids(test_db, "run-evidence", 9920)[0]
    artifact_id = _attach(
        test_db, _latest_run_id(test_db, case_id), '{"backend":"local"}'
    )
    acceptance_id = _acceptance_requirement_id(test_db, "run-evidence", "item-qa")

    context = qa_review_artifact_context(
        test_db,
        requirement_id=acceptance_id,
        run_id=_latest_run_id(test_db, acceptance_id),
    )
    assert context["evidence_state"] == "attached"
    # Everything the covered case captured, the screenshot included — the
    # acceptance is a verdict on that case, so that is its evidence.
    assert artifact_id in [item["artifact_id"] for item in context["artifacts"]]
    # The summary says where the pictures came from, so a reviewer is not left
    # to guess whether the acceptance captured them itself.
    assert "cases this acceptance covers" in context["evidence_summary"]
    # Each one keeps the requirement that captured it: reading an artifact is
    # authorized against its own requirement, so borrowed evidence that
    # claimed the acceptance's id would refuse to load on the page.
    borrowed = next(
        item for item in context["artifacts"] if item["artifact_id"] == artifact_id
    )
    assert borrowed["requirement_id"] == case_id
    assert borrowed["requirement_id"] != acceptance_id


def test_one_members_captures_never_back_another_members_acceptance(
    test_db,
) -> None:
    plan_id = _plan(test_db, "acceptance-isolation")
    _seed_run(
        test_db,
        run_id="run-isolated",
        stages=_stages(plan_id),
        members=(9921, 9922),
    )
    for member in (9921, 9922):
        _settle(test_db, run_id="run-isolated", stage="item-qa", member=member)
    first_case = _case_requirement_ids(test_db, "run-isolated", 9921)[0]
    second_case = _case_requirement_ids(test_db, "run-isolated", 9922)[0]
    first_artifact = _attach(
        test_db, _latest_run_id(test_db, first_case), '{"backend":"local"}'
    )
    second_artifact = _attach(
        test_db, _latest_run_id(test_db, second_case), '{"backend":"local"}'
    )

    # Both members settled at the same stage; each acceptance answers for its
    # own member's captures and no one else's.
    acceptance_ids = sorted(
        int(row["id"])
        for row in test_db.execute(
            "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
            "AND method_id IS NULL AND deployment_member_item_id=%s",
            ("run-isolated", 9922),
        ).fetchall()
    )
    context = qa_review_artifact_context(
        test_db,
        requirement_id=acceptance_ids[-1],
        run_id=_latest_run_id(test_db, acceptance_ids[-1]),
    )
    shown = [item["artifact_id"] for item in context["artifacts"]]
    assert second_artifact in shown
    assert first_artifact not in shown


def test_a_release_check_names_the_candidate_its_target_froze(test_db) -> None:
    # The candidate belongs to the run, not to the acceptance's own result,
    # and it is already on the execution target the check was materialized
    # against. "Revision not recorded" was a reader looking in one place.
    plan_id = _plan(test_db, "acceptance-revision")
    _seed_run(
        test_db, run_id="run-revision", stages=_stages(plan_id), members=(9923,)
    )
    _settle(test_db, run_id="run-revision", stage="item-qa", member=9923)
    acceptance_id = _acceptance_requirement_id(test_db, "run-revision", "item-qa")

    facts = requirement_facts(test_db, acceptance_id)
    assert facts["candidate_revision"] == "a" * 40
    # The environment comes from the same frozen document, because a stage's
    # target need not be a registered environment row the requirement names.
    assert facts["target_env"]
