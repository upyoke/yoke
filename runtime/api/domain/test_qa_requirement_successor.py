"""Supersession and operator reconciliation preserve a coherent correction chain."""

import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    record_case_verdict,
    seed_member_qa_case,
)
from runtime.api.fixtures.qa_declared_replacement_fixture import (
    corrected_case,
    declare,
    requirement_row,
)
from yoke_core.domain.qa_requirement_supersession import record_supersession
from yoke_core.domain.qa_requirement_successor import QaSuccessorError
from yoke_core.domain.qa_requirement_replacement import (
    QaReplacementError,
    point_at_replacement,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status


def chain(conn):
    old = seed_member_qa_case(conn, run_id="run-successor-chain", member_item_id=9811)
    record_case_verdict(conn, old, "fail", evidence=True)
    middle = corrected_case(conn, failed_id=old, case_key="first-correction")
    declare(conn, old, "first-correction", [middle])
    record_case_verdict(conn, middle, "fail", evidence=True)
    final = corrected_case(conn, failed_id=middle, case_key="final-correction")
    declare(conn, middle, "final-correction", [final])
    record_case_verdict(conn, final, "pass", evidence=True)
    return old, middle, final


def test_superseding_chain_moves_both_links_to_terminal_and_settles_gate(test_db):
    old, middle, final = chain(test_db)
    record_supersession(
        test_db,
        requirement_id=old,
        superseded_by_requirement_id=final,
        rationale="terminal correction passed",
    )
    row = requirement_row(test_db, old)
    assert (
        row["replacement_requirement_id"]
        == row["superseded_by_requirement_id"]
        == final
    )
    assert requirement_row(test_db, middle)["replacement_requirement_id"] == final
    from runtime.api.domain.test_qa_declared_replacement import _pass

    _pass(test_db, "run-successor-chain")
    status = deployment_qa_stage_status(
        test_db, run_id="run-successor-chain", stage_name="item-qa", member_item_id=9811
    )
    assert status["accepted"], status["reasons"]


def inconsistent(conn, old, final):
    conn.execute(
        "UPDATE qa_requirements SET superseded_by_requirement_id=%s, supersession_rationale=%s, supersession_source='agent', superseded_at=%s WHERE id=%s",
        (final, "original correction history", "2026-01-01T00:00:00Z", old),
    )
    conn.commit()


def test_registered_repair_preserves_history(test_db, monkeypatch):
    from yoke_contracts.api.function_call import FunctionCallRequest
    from yoke_core.domain.handlers.qa_requirement_supersede import (
        handle_qa_requirement_supersede,
    )
    from yoke_core.domain import db_helpers
    from yoke_core.domain import qa_requirement_successor

    old, middle, final = chain(test_db)
    inconsistent(test_db, old, final)
    prior = requirement_row(test_db, middle)

    class Borrowed:
        def __getattr__(self, name):
            return getattr(test_db, name)

        def close(self):
            pass

    monkeypatch.setattr(db_helpers, "connect", lambda: Borrowed())
    authorized = []
    monkeypatch.setattr(
        qa_requirement_successor,
        "authorize_reconciliation",
        lambda *args: authorized.append(args[2]),
    )
    request = FunctionCallRequest(
        function="qa.requirement.supersede",
        actor={"actor_id": "2", "session_id": "repair-operator"},
        target={"kind": "qa_requirement", "qa_requirement_id": old},
        payload={
            "superseded_by_requirement_id": final,
            "rationale": "unique terminal confirmed",
            "source": "operator",
            "reconcile": True,
        },
    )
    outcome = handle_qa_requirement_supersede(request)
    assert outcome.primary_success
    assert authorized == [old]
    row = requirement_row(test_db, old)
    assert (
        row["replacement_requirement_id"]
        == row["superseded_by_requirement_id"]
        == final
    )
    assert "original correction history" in row["supersession_rationale"]
    assert "actor=2 session=repair-operator" in row["supersession_rationale"]
    assert requirement_row(test_db, middle) == prior
    assert str(
        test_db.execute(
            "SELECT superseded_at FROM qa_requirements WHERE id=%s", (old,)
        ).fetchone()[0]
    ).startswith("2026-01-01")


@pytest.mark.parametrize("repair", [False, True])
def test_ambiguous_branches_refuse_before_writing(test_db, repair):
    old, middle, final = chain(test_db)
    other = corrected_case(test_db, failed_id=old, case_key="different-terminal")
    record_case_verdict(test_db, other, "pass", evidence=True)
    inconsistent(test_db, old, other)
    before = requirement_row(test_db, old)
    with pytest.raises(QaSuccessorError, match="replacement_graph_invalid"):
        record_supersession(
            test_db,
            requirement_id=old,
            superseded_by_requirement_id=final,
            rationale="cannot guess",
            source="operator",
            reconcile=repair,
        )
    assert requirement_row(test_db, old) == before


def test_inconsistent_links_require_explicit_reconciliation(test_db):
    old, _, final = chain(test_db)
    inconsistent(test_db, old, final)
    with pytest.raises(QaSuccessorError, match="ask an operator"):
        record_supersession(
            test_db,
            requirement_id=old,
            superseded_by_requirement_id=final,
            rationale="pass",
        )


def test_replacement_writer_rejects_conflicting_successor_links(test_db):
    old, middle, final = chain(test_db)
    other = corrected_case(test_db, failed_id=old, case_key="other-terminal")
    test_db.execute(
        "UPDATE qa_requirements SET superseded_by_requirement_id=%s WHERE id=%s",
        (other, middle),
    )
    with pytest.raises(QaReplacementError, match="replacement_graph_invalid"):
        point_at_replacement(test_db, old, middle)


def test_reconciliation_authority_uses_verified_session(test_db):
    from yoke_core.domain.session_operator_authority import (
        require_operator_or_steering_authority,
    )
    from yoke_core.domain.sessions_analytics import SessionError

    with pytest.raises(SessionError, match="live operator"):
        require_operator_or_steering_authority(
            test_db,
            actor_id=2,
            caller_session_id="missing-repair-session",
            project_id=1,
            action="QA successor reconciliation",
        )


def test_repaired_admitted_chain_allows_source_retirement(test_db):
    from runtime.api.domain.test_dash_post_deploy_review_isolation import _insert_dash
    from runtime.api.domain.test_qa_source_retirement import _corrected_item_requirement
    from runtime.api.fixtures.deployment_admitted_case_fixture import (
        deliver_with_failing_admitted_copy,
    )
    from yoke_core.domain.qa_requirement_supersession import supersede_requirement

    item_id = 9812
    _insert_dash(test_db, item_id=item_id, status="release")
    source_id, old, middle = deliver_with_failing_admitted_copy(
        test_db, item_id=item_id, run_id="run-retire-correction-chain", corrected=True
    )
    point_at_replacement(test_db, old, middle)
    test_db.commit()
    record_case_verdict(test_db, middle, "fail", evidence=True)
    final = corrected_case(test_db, failed_id=middle, case_key="terminal-correction")
    declare(test_db, middle, "terminal-correction", [final])
    test_db.commit()
    record_case_verdict(test_db, final, "pass", evidence=True)
    inconsistent(test_db, old, final)
    supersede_requirement(
        test_db,
        requirement_id=old,
        superseded_by_requirement_id=final,
        rationale="branches converge",
        source="operator",
        reconcile=True,
    )
    corrected_source = _corrected_item_requirement(test_db, source_id=source_id)
    receipt = supersede_requirement(
        test_db,
        requirement_id=source_id,
        superseded_by_requirement_id=corrected_source,
        rationale="terminal correction proves source",
    )
    assert receipt["run_replacement_requirement_id"] == final
