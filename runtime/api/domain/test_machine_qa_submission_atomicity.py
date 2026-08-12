"""Atomicity and replay coverage for hosted Machine QA submissions."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from runtime.api.domain.machine_qa_baseline_group_test_support import (
    baseline_group_request,
    configure_test_machine,
    materialize_installer_campaign,
)
from runtime.api.domain.machine_qa_test_support import FakeHostControl, make_conn
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.test_machine import (
    handle_verify_begin,
    handle_verify_submit,
)
from yoke_core.domain.handlers.test_machine_case import (
    handle_baseline_group_begin,
    handle_baseline_group_submit,
    handle_case_begin,
    handle_case_submit,
)
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_local_execution import (
    execute_machine_case_contract,
    execute_verification_contract,
)


VERIFY_ACTOR = ActorContext(actor_id="2", session_id="session-machine-submit-atomicity")
_ACTIVE_LEASE_COUNT_SQL = (
    "SELECT COUNT(*) FROM coordination_leases WHERE released_at IS NULL"
)


def _verify_request(
    function: str,
    payload: dict[str, Any],
    *,
    actor: ActorContext = VERIFY_ACTOR,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=actor,
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _case_requirement(conn: Any, item_id: int) -> int:
    return int(
        conn.execute(
            "SELECT id FROM qa_requirements "
            "WHERE item_id=%s AND method_id='machine-state-check' "
            "ORDER BY id LIMIT 1",
            (item_id,),
        ).fetchone()[0]
    )


def _run_and_artifact_counts(
    conn: Any,
    requirement_ids: list[int],
) -> tuple[int, int]:
    run_count = int(
        conn.execute(
            "SELECT COUNT(*) FROM qa_runs "
            "WHERE qa_requirement_id=ANY(%s) AND completed_at IS NOT NULL",
            (requirement_ids,),
        ).fetchone()[0]
    )
    artifact_count = int(
        conn.execute(
            "SELECT COUNT(*) FROM qa_artifacts a "
            "JOIN qa_runs r ON r.id=a.qa_run_id "
            "WHERE r.qa_requirement_id=ANY(%s)",
            (requirement_ids,),
        ).fetchone()[0]
    )
    return run_count, artifact_count


def _active_lease_count(conn: Any) -> int:
    return int(conn.execute(_ACTIVE_LEASE_COUNT_SQL).fetchone()[0])


def _local_case_submission(
    requirement_id: int,
    *,
    baseline_group: bool = False,
) -> Any:
    handler = handle_baseline_group_begin if baseline_group else handle_case_begin
    function = (
        "test_machine.baseline_group.begin"
        if baseline_group
        else "test_machine.case.begin"
    )
    register_host_control_factory(lambda _material: FakeHostControl())
    try:
        begun = handler(baseline_group_request(requirement_id, function=function))
        return execute_machine_case_contract(begun.result_payload["execution"])
    finally:
        clear_host_control_factory()


def _local_verification_submission() -> Any:
    register_host_control_factory(lambda _material: FakeHostControl())
    try:
        begun = handle_verify_begin(
            _verify_request(
                "test_machine.verify.begin",
                {"project": "yoke"},
            )
        )
        return execute_verification_contract(begun.result_payload["execution"])
    finally:
        clear_host_control_factory()


def _reject_release(*_args: Any, **_kwargs: Any) -> None:
    raise ValueError("lease release unavailable")


def test_case_submission_replay_reuses_canonical_run_and_evidence(
    test_db: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item_id = 4310
    materialize_installer_campaign(test_db, item_id=item_id)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    requirement_id = _case_requirement(test_db, item_id)
    submission = _local_case_submission(requirement_id)
    request = baseline_group_request(
        requirement_id,
        function="test_machine.case.submit",
        payload=submission.payload,
    )

    first = handle_case_submit(request)
    first_counts = _run_and_artifact_counts(test_db, [requirement_id])
    replay = handle_case_submit(request)

    assert first.primary_success, first.error
    assert replay.primary_success, replay.error
    assert replay.result_payload == first.result_payload
    assert _run_and_artifact_counts(test_db, [requirement_id]) == first_counts
    assert first_counts[0] == 1
    assert first_counts[1] >= 1


def test_baseline_group_replay_reuses_every_canonical_case(
    test_db: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = materialize_installer_campaign(test_db, item_id=4311)
    fresh = [row for row in rows if row["host_baseline"] == "fresh-host"]
    requirement_ids = [int(row["id"]) for row in fresh]
    configure_test_machine(test_db, tmp_path, monkeypatch)
    submission = _local_case_submission(
        requirement_ids[0],
        baseline_group=True,
    )
    request = baseline_group_request(
        requirement_ids[0],
        function="test_machine.baseline_group.submit",
        payload=submission.payload,
    )

    first = handle_baseline_group_submit(request)
    first_counts = _run_and_artifact_counts(test_db, requirement_ids)
    replay = handle_baseline_group_submit(request)

    assert first.primary_success, first.error
    assert replay.primary_success, replay.error
    assert replay.result_payload == first.result_payload
    assert _run_and_artifact_counts(test_db, requirement_ids) == first_counts
    assert first_counts[0] == len(requirement_ids)


def test_verification_replay_returns_original_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)
    submission = _local_verification_submission()
    request = _verify_request(
        "test_machine.verify.submit",
        {"project": "yoke", **submission.payload},
    )

    first = handle_verify_submit(request)
    later_submission = _local_verification_submission()
    later_payload = {"project": "yoke", **later_submission.payload}
    later_payload["status"] = "error"
    later_payload["checks"] = [{**later_payload["checks"][0], "ok": False}]
    later_payload["error_code"] = "connection_check_failed"
    later = handle_verify_submit(
        _verify_request("test_machine.verify.submit", later_payload)
    )
    replay = handle_verify_submit(request)

    assert first.primary_success, first.error
    assert later.result_payload["status"] == "error"
    assert replay.primary_success, replay.error
    assert replay.result_payload == first.result_payload


def test_verification_replay_rejects_another_lease_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)
    submission = _local_verification_submission()
    payload = {"project": "yoke", **submission.payload}
    accepted = handle_verify_submit(
        _verify_request("test_machine.verify.submit", payload)
    )

    assert accepted.primary_success, accepted.error
    unauthorized = [
        (
            ActorContext(actor_id="3", session_id=VERIFY_ACTOR.session_id),
            "different actor",
        ),
        (
            ActorContext(
                actor_id=VERIFY_ACTOR.actor_id,
                session_id="different-session",
            ),
            "different session",
        ),
    ]
    for actor, message in unauthorized:
        replay = handle_verify_submit(
            _verify_request(
                "test_machine.verify.submit",
                payload,
                actor=actor,
            )
        )
        assert not replay.primary_success
        assert message in replay.error.message


def test_invalid_group_submission_preserves_lease_without_runs(
    test_db: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = materialize_installer_campaign(test_db, item_id=4312)
    fresh = [row for row in rows if row["host_baseline"] == "fresh-host"]
    requirement_ids = [int(row["id"]) for row in fresh]
    configure_test_machine(test_db, tmp_path, monkeypatch)
    submission = _local_case_submission(
        requirement_ids[0],
        baseline_group=True,
    )
    invalid_payload = deepcopy(submission.payload)
    invalid_payload["results"][-1]["evidence"]["machine"] = "wrong-machine"

    rejected = handle_baseline_group_submit(
        baseline_group_request(
            requirement_ids[0],
            function="test_machine.baseline_group.submit",
            payload=invalid_payload,
        )
    )

    assert not rejected.primary_success
    assert "wrong test machine" in rejected.error.message
    assert _run_and_artifact_counts(test_db, requirement_ids) == (0, 0)
    assert _active_lease_count(test_db) == 1


def test_case_release_failure_rolls_back_run_and_evidence(
    test_db: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item_id = 4313
    materialize_installer_campaign(test_db, item_id=item_id)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    requirement_id = _case_requirement(test_db, item_id)
    submission = _local_case_submission(requirement_id)

    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_execution_protocol.release_lease",
        _reject_release,
    )
    rejected = handle_case_submit(
        baseline_group_request(
            requirement_id,
            function="test_machine.case.submit",
            payload=submission.payload,
        )
    )

    assert not rejected.primary_success
    assert "lease release unavailable" in rejected.error.message
    assert _run_and_artifact_counts(test_db, [requirement_id]) == (0, 0)
    assert _active_lease_count(test_db) == 1


def test_verification_release_failure_rolls_back_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)
    submission = _local_verification_submission()

    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_execution_protocol.release_lease",
        _reject_release,
    )
    rejected = handle_verify_submit(
        _verify_request(
            "test_machine.verify.submit",
            {"project": "yoke", **submission.payload},
        )
    )

    assert not rejected.primary_success
    receipt = conn.execute(
        "SELECT status,receipt_json FROM test_machine_verifications WHERE project_id=1"
    ).fetchone()
    assert receipt["status"] == "configured_unverified"
    assert receipt["receipt_json"] == "{}"
    assert _active_lease_count(conn) == 1
