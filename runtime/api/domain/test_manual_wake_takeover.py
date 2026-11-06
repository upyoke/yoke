"""A release takeover moves QA without repeating its unchanged notice."""

from runtime.api.domain import deployment_run_target_takeover_test_support as takeover
from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    HOLDER_A,
    HOLDER_B,
    _claim,
    _project,
    seed_session,
)
from yoke_core.domain.deployment_qa_manual_wake import (
    manual_wake_requirements,
    wake_manual_requirement_owners,
)
from yoke_core.domain.deployment_qa_stage_wake_state import _latest_notices
from yoke_core.domain.work_claim_targets import make_item_target


def _notices(conn):
    return [
        row[0]
        for row in conn.execute(
            "SELECT message_id FROM session_messages "
            "WHERE idempotency_key LIKE 'deployment-qa-manual-wait:%'"
        ).fetchall()
    ]


def _wake(conn, run_id):
    project = conn.execute(
        "SELECT project_id FROM items WHERE id=%s", (takeover.WAITING,)
    ).fetchone()[0]
    entries = manual_wake_requirements(
        conn,
        run_id=run_id,
        stage_name=takeover.ITEM_QA_STAGE,
        item_ids=[takeover.WAITING],
        project_slug="yoke",
    )
    assert len(entries) == 1
    assert wake_manual_requirement_owners(conn, entries, project_id=project) == []


def test_takeover_keeps_notice_but_changed_evidence_or_holder_wakes(
    test_db, monkeypatch
):
    _project(test_db)
    requirements = takeover._seed_old(test_db, run_qa=False)
    takeover._close_passed(test_db)
    requirement = requirements[takeover.WAITING]
    test_db.execute(
        "UPDATE qa_requirements SET wake_path='manual',wake_evidence='one day of traffic' WHERE id=%s",
        (requirement,),
    )
    seed_session(test_db, HOLDER_A)
    _claim(
        test_db,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(takeover.WAITING).scope_json(),
    )
    test_db.commit()
    _wake(test_db, takeover.OLD)
    first = _notices(test_db)
    assert len(first) == 1
    takeover._seed_new(test_db)
    takeover._contains(monkeypatch)
    assert takeover._take_over(test_db) == takeover.OLD
    _wake(test_db, takeover.NEW)
    assert _notices(test_db) == first
    assert takeover.WAITING in _latest_notices(
        test_db,
        run_id=takeover.NEW,
        stage_name=takeover.ITEM_QA_STAGE,
    )
    test_db.execute(
        "UPDATE qa_requirements SET wake_evidence='two days of traffic' WHERE id=%s",
        (requirement,),
    )
    test_db.commit()
    _wake(test_db, takeover.NEW)
    assert len(_notices(test_db)) == 2
    test_db.execute(
        "UPDATE work_claims SET released_at=CURRENT_TIMESTAMP WHERE session_id=%s",
        (HOLDER_A,),
    )
    seed_session(test_db, HOLDER_B)
    _claim(
        test_db,
        session_id=HOLDER_B,
        target_kind="item",
        scope_json=make_item_target(takeover.WAITING).scope_json(),
    )
    test_db.commit()
    _wake(test_db, takeover.NEW)
    assert len(_notices(test_db)) == 3
