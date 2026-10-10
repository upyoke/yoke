"""Stored QA replacement links stay valid, and broken ones are named."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.test_qa_requirement_target_rebind import (
    _stamp_requirement,
    _yoke_development,
)
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    record_case_verdict,
    seed_member_qa_case,
)
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.fixtures.qa_declared_replacement_fixture import (
    corrected_case,
    declare,
)
from yoke_core.domain.qa_done_gate_refusal import done_gate_refusal_errors
from yoke_core.domain.qa_obligation_settlement import effective_requirement
from yoke_core.domain.qa_replacement_scope_guard import (
    LINKED_SCOPE_CHANGE_CODE,
    broken_links_touching,
)
from yoke_core.domain.qa_requirement_config_update import apply_requirement_update
from yoke_core.domain.qa_requirement_supersession import record_supersession
from yoke_core.domain.qa_requirement_target_rebind import (
    QaRebindError,
    rebind_requirement,
)

RUN = "run-link-scope"
ITEM = 9871


def _linked(conn):
    old = seed_member_qa_case(conn, run_id=RUN, member_item_id=ITEM)
    record_case_verdict(conn, old, "fail", evidence=True)
    corrected = corrected_case(conn, failed_id=old, case_key="corrected")
    declare(conn, old, "corrected", [corrected])
    return old, corrected


def _scope_rule_moved(conn, requirement_id):
    """A row that answered under the old rule but not the current one."""
    conn.execute(
        "UPDATE qa_requirements SET host_baseline='fresh-host' WHERE id=%s",
        (requirement_id,),
    )
    conn.commit()


def _column(conn, requirement_id, column):
    return conn.execute(
        f"SELECT {column} FROM qa_requirements WHERE id=%s", (requirement_id,)
    ).fetchone()[0]


def test_update_refuses_a_scope_change_on_a_linked_row(test_db):
    old, corrected = _linked(test_db)
    result = apply_requirement_update(
        test_db, corrected, "blocking_mode", "non_blocking"
    )
    assert not result.ok
    assert result.error_code == LINKED_SCOPE_CHANGE_CODE
    assert (
        f"requirement #{old} replacement_requirement_id -> #{corrected}"
        in result.message
    )
    assert "--reconcile --source operator" in result.message
    assert _column(test_db, corrected, "blocking_mode") == "blocking"


def test_rebind_refuses_a_target_change_on_a_linked_row():
    with test_database() as conn:
        environment_id = _yoke_development(conn)
        old = _stamp_requirement(conn, item_id=9872, environment_id=environment_id)
        corrected = corrected_case(conn, failed_id=old, case_key="corrected")
        conn.execute(
            "UPDATE qa_requirements SET replacement_requirement_id=%s WHERE id=%s",
            (corrected, old),
        )
        settings = json.loads(
            conn.execute(
                "SELECT settings FROM environments WHERE id=%s", (environment_id,)
            ).fetchone()[0]
            or "{}"
        )
        settings.setdefault("hosts", {})["app"] = "https://app.example.test"
        conn.execute(
            "UPDATE environments SET settings=%s WHERE id=%s",
            (json.dumps(settings), environment_id),
        )
        conn.commit()
        digest = _column(conn, corrected, "execution_target_digest")
        with pytest.raises(QaRebindError, match=LINKED_SCOPE_CHANGE_CODE):
            rebind_requirement(
                conn, requirement_id=corrected, rationale="declared host", actor_id=2
            )
        assert _column(conn, corrected, "execution_target_digest") == digest


def test_done_refusal_names_the_graph_error_not_missing_proof(test_db):
    old, corrected = _linked(test_db)
    _scope_rule_moved(test_db, corrected)
    with pytest.raises(ValueError) as caught:
        effective_requirement(test_db, old)
    graph_error = str(caught.value)
    assert graph_error.startswith("replacement_graph_invalid:")
    assert "--reconcile --source operator" in graph_error
    row = {
        "id": old,
        "qa_kind": "browser-check",
        "qa_phase": "post_deploy",
        "deployment_run_id": RUN,
        "target_env": "prod",
        "execution_target_json": "",
        "replacement_graph_error": graph_error,
    }
    text = "\n".join(done_gate_refusal_errors(test_db, [row], name="YOK-1"))
    assert graph_error in text
    assert "missing_target_proof" not in text
    assert "not accepted on the completion run" not in text


def test_reconcile_replaces_a_link_that_no_longer_answers(test_db):
    old, corrected = _linked(test_db)
    _scope_rule_moved(test_db, corrected)
    (finding,) = broken_links_touching(test_db, [old])
    assert "host baseline differs" in finding
    answer = corrected_case(test_db, failed_id=old, case_key="same-scope-answer")
    record_case_verdict(test_db, answer, "pass", evidence=True)
    record_supersession(
        test_db,
        requirement_id=old,
        superseded_by_requirement_id=answer,
        rationale="the earlier correction moved host baseline",
        source="operator",
        reconcile=True,
    )
    test_db.commit()
    assert _column(test_db, old, "replacement_requirement_id") == answer
    assert broken_links_touching(test_db, [old, corrected, answer]) == []


@pytest.mark.parametrize("surface", ["terminalize", "status"])
def test_cancelling_a_run_retracts_its_outstanding_member_copies(test_db, surface):
    outstanding = seed_member_qa_case(test_db, run_id=RUN, member_item_id=ITEM)
    if surface == "terminalize":
        from yoke_core.domain.deployment_run_terminalization import terminalize_run_on

        terminalize_run_on(
            test_db,
            RUN,
            disposition="cancelled",
            reason="superseded by the next release",
            actor_id=2,
            session_id="canceller",
        )
        test_db.commit()
    else:
        from yoke_core.domain.deployment_runs_crud_mutate import cmd_update

        assert cmd_update(RUN, "status", "cancelled") is None
    assert _column(test_db, outstanding, "retracted_at")
    assert "cancelled" in _column(test_db, outstanding, "retraction_rationale")
