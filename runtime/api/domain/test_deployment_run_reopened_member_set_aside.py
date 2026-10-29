"""A member reopened after its run froze is set aside, not a resume failure."""

from typing import Any

import pytest

from runtime.api.domain.test_deployment_delivery_close_out_notice import _project
from runtime.api.domain.test_no_obligation_member_close_out import (
    _no_obligation,
    _ready_member,
)
from runtime.api.domain.test_run_success_member_settlement import (
    _claim_held,
    _executing_run,
)
from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement
from runtime.api.fixtures.carried_release_candidate import (
    record_landing_receipt,
    release_repository,
    serve_repository,
)
from yoke_core.domain.dash_execution import record_dash_evidence
from yoke_core.domain.deployment_run_member_removal import REOPENED_REMOVED_BY
from yoke_core.domain.deployment_run_membership_removals import membership_removals
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.deployment_run_frozen_composition import (
    frozen_composition_verdict,
)
from yoke_core.domain.deployment_runs_validation import cmd_validate_composition

REOPENED = 9971
SIBLING = 9972
RUN = "run-reopened-member"
REWORK_STAGE = "reviewing-implementation"


def _land(conn: Any, repo: Any, item_id: int, sha: str) -> None:
    record_landing_receipt(conn, item_id, branch=f"member-{item_id}", tip=sha)
    record_dash_evidence(
        conn,
        item_id=item_id,
        result_summary="landed",
        verification_summary="checked",
        verification_status="passed",
        commit_sha=sha,
        merge_sha=sha,
        touched_files=["release.txt"],
        tree_root=str(repo),
        tree_head_sha=sha,
    )


def _frozen_run_with_reopened_member(
    conn: Any, tmp_path: Any, monkeypatch: Any, *, reopened_sha: str, settled: bool
) -> None:
    """Both members landed and deployed; one reopened for rework afterwards."""
    _isolate_status_effects(monkeypatch)
    _project(conn)
    repo, frozen, correction = release_repository(tmp_path, "reopened")
    serve_repository(monkeypatch, repo)
    for item in (REOPENED, SIBLING):
        _ready_member(conn, item, f"holder-{item}")
        _no_obligation(conn, item, reason="no runtime obligation")
    if not settled:
        insert_qa_requirement(
            conn,
            item_id=REOPENED,
            qa_kind="manual",
            qa_phase="post_deploy",
            blocking_mode="blocking",
            instructions="unanswered member check",
        )
    _land(conn, repo, REOPENED, correction if reopened_sha == "correction" else frozen)
    _land(conn, repo, SIBLING, frozen)
    _executing_run(conn, RUN, (REOPENED, SIBLING))
    conn.execute(
        "UPDATE deployment_runs SET release_lineage=%s,"
        "composition_frozen_at='2026-10-16T20:00:00Z' WHERE id=%s",
        (frozen, RUN),
    )
    from yoke_core.domain.item_status_transitions import record_item_transition

    conn.execute("UPDATE items SET status=%s WHERE id=%s", (REWORK_STAGE, REOPENED))
    assert record_item_transition(
        conn, item_id=REOPENED, from_status="release",
        to_status=REWORK_STAGE, source="reopen for rework",
    )
    conn.commit()


def _redrive_verdict(conn: Any) -> tuple[bool, str]:
    """What an execution-context re-drive of the frozen run answers."""
    verdict = frozen_composition_verdict(conn, RUN)
    if verdict[0]:
        conn.commit()
    else:
        conn.rollback()
    return verdict


#: Both resume paths: the full validator, and a re-drive of the frozen run.
RESUMES = pytest.mark.parametrize(
    "resume",
    [lambda conn: cmd_validate_composition(RUN), _redrive_verdict],
    ids=["validate_composition", "frozen_redrive"],
)


def _members(conn: Any) -> set[int]:
    return {
        int(row["item_id"])
        for row in conn.execute(
            "SELECT item_id FROM deployment_run_items WHERE run_id=%s", (RUN,)
        ).fetchall()
    }


@RESUMES
@pytest.mark.parametrize("settled", [True, False])
def test_resume_sets_aside_a_reopened_member_outside_the_lineage(
    test_db, tmp_path, monkeypatch, settled, resume
):
    _frozen_run_with_reopened_member(
        test_db, tmp_path, monkeypatch, reopened_sha="correction", settled=settled
    )

    ok, message = resume(test_db)

    assert ok, message
    assert "Set aside reopened members awaiting a later release" in message
    assert _members(test_db) == {SIBLING}
    (removal,) = membership_removals(test_db, RUN)
    assert removal["item_id"] == REOPENED
    assert "awaiting a later release" in removal["reason"]
    assert (
        test_db.execute("SELECT status FROM items WHERE id=%s", (REOPENED,)).fetchone()[
            "status"
        ]
        == REWORK_STAGE
    )
    assert _claim_held(test_db, REOPENED)


def test_removal_notice_tells_a_reopened_owner_to_continue_rework():
    from yoke_core.domain.deployment_member_removal_notice import (
        removal_notice_body,
    )

    body = removal_notice_body(
        run_id=RUN,
        public_ref="YOK-1",
        reason="awaiting a later release",
        removed_by=REOPENED_REMOVED_BY,
        red=(),
    )
    assert "Continue its rework" in body and "yoke merge item" in body


@RESUMES
def test_resume_keeps_a_reopened_member_whose_candidate_is_contained(
    test_db, tmp_path, monkeypatch, resume
):
    _frozen_run_with_reopened_member(
        test_db, tmp_path, monkeypatch, reopened_sha="frozen", settled=True
    )

    ok, message = resume(test_db)

    assert ok, message
    assert _members(test_db) == {REOPENED, SIBLING}
    assert not membership_removals(test_db, RUN)


@RESUMES
def test_resume_refuses_a_reopened_member_with_undetermined_containment(
    test_db, tmp_path, monkeypatch, resume
):
    from yoke_core.domain import deployment_run_candidate_containment as containment

    _frozen_run_with_reopened_member(
        test_db, tmp_path, monkeypatch, reopened_sha="correction", settled=True
    )

    def undetermined(self, sha):
        return containment.ContainmentVerdict(
            containment.UNDETERMINED,
            reason="source repository unreadable",
            recovery="restore the checkout mapping and resume",
        )

    monkeypatch.setattr(containment.CandidateContainment, "contains", undetermined)

    ok, message = resume(test_db)

    assert not ok
    assert "containment of its current candidate is undetermined" in message
    assert "restore the checkout mapping and resume" in message
    assert _members(test_db) == {REOPENED, SIBLING}
    assert not membership_removals(test_db, RUN)


def test_settlement_sets_aside_a_reopened_member(test_db, tmp_path, monkeypatch):
    _frozen_run_with_reopened_member(
        test_db, tmp_path, monkeypatch, reopened_sha="correction", settled=True
    )

    assert cmd_update(RUN, "status", "succeeded") is None

    (removal,) = membership_removals(test_db, RUN)
    assert removal["item_id"] == REOPENED
    assert "left delivery readiness" in removal["reason"]
    assert (
        test_db.execute(
            "SELECT status FROM deployment_runs WHERE id=%s", (RUN,)
        ).fetchone()["status"]
        == "succeeded"
    )
    assert (
        test_db.execute("SELECT status FROM items WHERE id=%s", (SIBLING,)).fetchone()[
            "status"
        ]
        == "done"
    )
    assert _claim_held(test_db, REOPENED)
