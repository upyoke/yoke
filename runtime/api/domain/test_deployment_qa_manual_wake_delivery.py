"""Manual-wake QA notices, delivered for real through the stage driver.

A member with open ``wake_path: manual`` requirements gets one notice per
requirement, keyed by run, stage, member and requirement, so re-driving the
same stage never sends a second one. A parked claim holder is still the
recipient; a member nobody holds reaches the project's steering seat.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

from runtime.api.domain.coordination_claim_test_support import PROJECT_YOKE
from runtime.api.domain.test_deployment_qa_manual_wake import EVIDENCE, _requirement
from runtime.api.domain.test_deployment_qa_stage_dispatch_wake import (
    _WAITING,
    _member,
    _run,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    HOLDER_B,
    _bodies,
    _claim,
    _project,
    _recipients,
    seed_session,
)
from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_wake import (
    DEPLOYMENT_QA_STAGE_WAIT_PREFIX,
    stage_wait_idempotency_key,
)
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.work_claim_targets import make_item_target, make_steering_target


def _drive(conn: Any, run_id: str) -> int:
    with mock.patch(
        "yoke_core.domain.deployment_qa_stage_gate.deployment_qa_stage_status",
        return_value=_WAITING,
    ):
        rc, _diag = materialize_and_gate_deployment_qa_stage(
            conn, {"name": "item-qa", "scope": "item"}, run_id=run_id
        )
    return rc


def _manual_key(run_id: str, member: int, requirement_id: int) -> str:
    return stage_wait_idempotency_key(
        run_id, "item-qa", member, f"manual-{requirement_id}"
    )


def _wait_keys(conn: Any, run_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT idempotency_key FROM session_messages WHERE idempotency_key LIKE %s "
        "ORDER BY idempotency_key",
        (f"{DEPLOYMENT_QA_STAGE_WAIT_PREFIX}{run_id}:%",),
    ).fetchall()
    return [row["idempotency_key"] if hasattr(row, "keys") else row[0] for row in rows]


def test_parked_holder_gets_one_wake_per_manual_requirement(test_db: Any) -> None:
    _project(test_db)
    _run(test_db, "run-manual-wd-1")
    member = 9711
    _member(test_db, "run-manual-wd-1", member)
    seed_session(test_db, HOLDER_A)
    test_db.execute(
        "UPDATE harness_sessions SET mode='parked' WHERE session_id=%s", (HOLDER_A,)
    )
    _claim(
        test_db,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(member).scope_json(),
    )
    for requirement_id in (97111, 97112):
        _requirement(
            test_db,
            requirement_id=requirement_id,
            run_id="run-manual-wd-1",
            member=member,
            wake_path="manual",
        )

    assert _drive(test_db, "run-manual-wd-1") == -4
    assert _drive(test_db, "run-manual-wd-1") == -4, "re-driving the same stage"

    keys = [_manual_key("run-manual-wd-1", member, r) for r in (97111, 97112)]
    assert _wait_keys(test_db, "run-manual-wd-1") == keys, (
        "exactly one notice per manual requirement, and no ordinary stage wake"
    )
    ref = render_item_ref(test_db, member)
    for key, requirement_id in zip(keys, (97111, 97112)):
        assert _recipients(test_db, key) == [HOLDER_A]
        [body] = _bodies(test_db, key)
        assert f"#{requirement_id} (case real-traffic)" in body
        assert f"{ref}'s claim holder" in body
        assert "Check this evidence with a registered read" in body
        assert EVIDENCE in body
        assert (
            f"yoke qa plan run --deployment-run-id run-manual-wd-1 --stage "
            f"item-qa --member {ref} --project yoke"
        ) in body
        assert "waive or remove the case" in body


def test_holderless_member_routes_its_manual_wake_to_steering(test_db: Any) -> None:
    _project(test_db)
    _run(test_db, "run-manual-wd-2")
    member = 9712
    _member(test_db, "run-manual-wd-2", member)
    seed_session(test_db, HOLDER_B)
    _claim(
        test_db,
        session_id=HOLDER_B,
        target_kind="steering",
        scope_json=make_steering_target(PROJECT_YOKE).scope_json(),
    )
    _requirement(
        test_db,
        requirement_id=97121,
        run_id="run-manual-wd-2",
        member=member,
        wake_path="manual",
    )

    _drive(test_db, "run-manual-wd-2")

    key = _manual_key("run-manual-wd-2", member, 97121)
    assert _recipients(test_db, key) == [HOLDER_B]
    [body] = _bodies(test_db, key)
    assert "project steering seat (its claim holder is gone)" in body


def test_unaddressable_manual_wake_names_the_staffing_step(
    test_db: Any, capsys: Any
) -> None:
    _project(test_db)
    _run(test_db, "run-manual-wd-3")
    _member(test_db, "run-manual-wd-3", 9713)
    _requirement(
        test_db,
        requirement_id=97131,
        run_id="run-manual-wd-3",
        member=9713,
        wake_path="manual",
    )

    _drive(test_db, "run-manual-wd-3")

    out = capsys.readouterr().out
    assert "manual-wake requirement #97131 has no live claim holder" in out
    assert "Staff the item, then re-drive the run." in out
    assert _wait_keys(test_db, "run-manual-wd-3") == []
