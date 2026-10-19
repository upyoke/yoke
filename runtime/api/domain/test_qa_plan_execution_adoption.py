"""Restaffing preserves QA captures while transferring explicit authority."""

import pytest

from runtime.api.fixtures.dispatch_actor import register_session_actor
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.fixtures.qa_captured_plan_review_fixture import captured_plan_review
from runtime.api.fixtures.session_holdings import insert_item_claim
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_plan_execution_adoption import adopt_execution
from yoke_core.domain.qa_plan_execution_authority import require_plan_execution_owner
from yoke_core.domain.qa_plan_execution_store import lock_plan_execution
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.qa_plan_review_submission import submit_plan_review
from yoke_core.domain.schema_init_tables import create_governed_tables


def _setup(conn, *, ended=True, claim=True, stamp="terminated_at"):
    execution, requirement, capture = captured_plan_review(conn, 4901)
    create_governed_tables(conn)
    register_session_actor(conn, execution["session_id"])
    actor = register_session_actor(conn, "successor-session")
    if ended:
        assert stamp in {"terminated_at", "ended_at"}
        conn.execute(
            f"UPDATE harness_sessions SET {stamp}=CURRENT_TIMESTAMP WHERE session_id=%s",
            (execution["session_id"],),
        )
    conn.commit()
    if claim:
        insert_item_claim(conn, "successor-session", 4901)
        conn.commit()
    return execution, requirement, capture, str(actor)


def _adopt(conn, execution, actor, **kwargs):
    return adopt_execution(
        conn,
        execution["id"],
        item_id=4901,
        actor_id=actor,
        session_id="successor-session",
        reason="Continue captured QA after restaffing",
        **kwargs,
    )


@pytest.mark.parametrize("stamp", ["ended_at", "terminated_at"])
@pytest.mark.parametrize("state", ["awaiting_agent_review", "aborted"])
def test_successor_reviews_existing_capture_and_preserves_terminal_history(
    stamp, state
):
    with test_database() as conn:
        execution, requirement, capture, actor = _setup(conn, stamp=stamp)
        bundle = begin_plan_review(conn, execution)
        conn.execute(
            "UPDATE qa_plan_executions SET state=%s WHERE id=%s",
            (state, execution["id"]),
        )
        conn.commit()
        before = lock_plan_execution(conn, execution["id"])
        receipt = _adopt(conn, execution, actor)
        assert receipt["previous_session_id"] == execution["session_id"]
        adopted = lock_plan_execution(conn, execution["id"])
        for key in (
            "roster_digest",
            "cursor_ordinal",
            "execution_target_digest",
            "machine_lease_id",
            "state",
        ):
            assert adopted[key] == before[key]
        require_plan_execution_owner(
            adopted,
            conn=conn,
            item_id=4901,
            actor_id=actor,
            session_id="successor-session",
            reviewing=True,
        )
        recovered = begin_plan_review(
            conn, adopted, completed_captures_only=state == "aborted"
        )
        assert recovered["bundle_id"] == bundle["bundle_id"]
        assert recovered["bundle_digest"] == bundle["bundle_digest"]
        assert recovered["cases"][0]["capture_run_id"] == capture
        submit_plan_review(
            conn,
            adopted,
            bundle_id=recovered["bundle_id"],
            bundle_digest=recovered["bundle_digest"],
            verdicts=[
                {
                    "requirement_id": requirement,
                    "verdict": "pass",
                    "rationale": "Captured evidence satisfies the case.",
                }
            ],
            reviewer_actor_id=actor,
            reviewer_session_id="successor-session",
        )
        assert (
            query_one(conn, "SELECT verdict FROM qa_runs WHERE id=%s", (capture,))[
                "verdict"
            ]
            == "pass"
        )
        assert lock_plan_execution(conn, execution["id"])["state"] == (
            "aborted" if state == "aborted" else "completed"
        )
        audit = query_one(
            conn,
            "SELECT * FROM qa_plan_execution_adoptions WHERE id=%s",
            (receipt["adoption_id"],),
        )
        assert audit["previous_session_id"] == execution["session_id"]
        assert audit["session_id"] == "successor-session"
        assert audit["reason"] == "Continue captured QA after restaffing"
        assert _adopt(conn, execution, actor)["state"] == "already_owned"
        assert (
            conn.execute("SELECT COUNT(*) FROM qa_plan_execution_adoptions").fetchone()[
                0
            ]
            == 1
        )


@pytest.mark.parametrize("mode", ["dash", "parked"])
def test_live_or_parked_predecessor_cannot_be_adopted(mode):
    with test_database() as conn:
        execution, _, _, actor = _setup(conn, ended=False)
        conn.execute(
            "UPDATE harness_sessions SET mode=%s WHERE session_id=%s",
            (mode, execution["session_id"]),
        )
        conn.commit()
        with pytest.raises(ValueError, match="qa_adoption_owner_live"):
            _adopt(conn, execution, actor)
        conn.rollback()
        assert (
            lock_plan_execution(conn, execution["id"])["session_id"]
            == execution["session_id"]
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM qa_plan_execution_adoptions").fetchone()[
                0
            ]
            == 0
        )


def test_nonholder_cannot_adopt_ended_execution():
    with test_database() as conn:
        execution, _, _, actor = _setup(conn, claim=False)
        with pytest.raises(ValueError, match="qa_adoption_claim_required"):
            _adopt(conn, execution, actor)


def test_adoption_does_not_grant_old_owner_mutation_authority():
    with test_database() as conn:
        execution, _, _, actor = _setup(conn)
        _adopt(conn, execution, actor)
        adopted = lock_plan_execution(conn, execution["id"])
        with pytest.raises(ValueError, match="qa_execution_owner_mismatch"):
            require_plan_execution_owner(
                adopted,
                item_id=4901,
                actor_id=execution["actor_id"],
                session_id=execution["session_id"],
            )


def test_successor_continues_existing_command_cursor_without_replay():
    from runtime.api.domain.test_qa_plan_execution_authority import (
        _materialize_two_cases,
        _result,
    )
    from yoke_core.domain.qa_plan_execution_state import (
        begin_plan_execution,
        advance_plan_execution,
    )

    with test_database() as conn:
        requirements = _materialize_two_cases(conn, item_id=4901)
        create_governed_tables(conn)
        actor = str(register_session_actor(conn, "successor-session"))
        register_session_actor(conn, "predecessor")
        execution = begin_plan_execution(
            conn,
            item_id=4901,
            transition_id="implemented",
            actor_id=actor,
            session_id="predecessor",
        )
        advance_plan_execution(
            conn,
            execution,
            ordinal=0,
            requirement_id=requirements[0],
            result=_result(requirements[0]),
        )
        conn.execute(
            "UPDATE harness_sessions SET ended_at=CURRENT_TIMESTAMP WHERE session_id='predecessor'"
        )
        conn.commit()
        insert_item_claim(conn, "successor-session", 4901)
        _adopt(conn, execution, actor)
        resumed = begin_plan_execution(
            conn,
            item_id=4901,
            transition_id="implemented",
            actor_id=actor,
            session_id="successor-session",
        )
        assert resumed["id"] == execution["id"]
        assert resumed["cursor_ordinal"] == 1


def test_deployment_execution_uses_its_member_claim_and_preserves_capture():
    with test_database() as conn:
        execution, _, _, actor = _setup(conn)
        conn.execute(
            "UPDATE qa_plan_executions SET item_id=NULL,transition_id=NULL,deployment_run_id='release-run',deployment_stage='production-qa',deployment_member_item_id=4901 WHERE id=%s",
            (execution["id"],),
        )
        conn.commit()
        receipt = adopt_execution(
            conn,
            execution["id"],
            deployment_run_id="release-run",
            actor_id=actor,
            session_id="successor-session",
            reason="Continue deployment review",
        )
        assert receipt["state"] == "adopted"
        adopted = lock_plan_execution(conn, execution["id"])
        assert adopted["roster_digest"] == execution["roster_digest"]
        assert adopted["deployment_member_item_id"] == 4901


def test_missing_predecessor_or_wrong_subject_never_transfers():
    with test_database() as conn:
        execution, _, _, actor = _setup(conn)
        with pytest.raises(ValueError, match="different item"):
            adopt_execution(
                conn,
                execution["id"],
                item_id=4902,
                actor_id=actor,
                session_id="successor-session",
                reason="Restaffed QA",
            )
        conn.rollback()
        conn.execute(
            "UPDATE qa_plan_executions SET session_id='unregistered-predecessor' WHERE id=%s",
            (execution["id"],),
        )
        conn.commit()
        with pytest.raises(ValueError, match="qa_adoption_owner_unverified"):
            _adopt(conn, execution, actor)
        conn.rollback()
        assert (
            conn.execute("SELECT COUNT(*) FROM qa_plan_execution_adoptions").fetchone()[
                0
            ]
            == 0
        )
