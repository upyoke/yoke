from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runtime.api.domain.machine_qa_baseline_group_test_support import (
    baseline_group_request,
    configure_test_machine,
    materialize_installer_campaign,
)
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from yoke_cli.commands.adapters import test_machine as test_machine_cli
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_contracts.machine_config.test_machine import (
    test_machine_capability_type as _machine_type,
)
from yoke_core.domain.handlers.machine_qa_case import (
    handle_baseline_group_begin,
    handle_baseline_group_execute,
    handle_baseline_group_submit,
)
from yoke_core.domain.handlers.machine_qa_execution_abort import (
    handle_baseline_group_abort,
)
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_local_execution import (
    LocalHostControlSubmission,
    execute_machine_case_contract,
)


def test_baseline_group_begin_local_submit_executes_server_discovered_cases(
    test_db: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = materialize_installer_campaign(test_db, item_id=4201)
    fresh = [row for row in rows if row["host_baseline"] == "fresh-host"]
    shell = [row for row in rows if row["host_baseline"] == "shell-preconfigured"]
    assert [row["plan_case_key"] for row in fresh] == [
        "default-add-yoke-to-my-path",
        "preview-then-add",
        "skip-path-repair",
        "ssh-only-path-missing",
        "re-run-after-path-fix",
        "full-curl-bash-in-terminal-app-wizard-left-by-quit",
    ]
    assert [row["plan_case_key"] for row in shell] == [
        "already-on-path",
        "one-shot-ssh-command-after-path-repair",
        "one-shot-ssh-path-after-full-onboard",
        "path-repair-writes-both-startup-files",
        "re-run-the-installer-from-a-fresh-login-shell-after-path-repair",
    ]
    assert {row["id"] for row in fresh}.isdisjoint({row["id"] for row in shell})

    expected_ids = [int(row["id"]) for row in fresh]
    configure_test_machine(test_db, tmp_path, monkeypatch)
    control = FakeHostControl()
    register_host_control_factory(lambda _material: control)
    try:
        begun = handle_baseline_group_begin(
            baseline_group_request(
                int(fresh[0]["id"]),
                function="test_machine.baseline_group.begin",
            )
        )
        assert begun.primary_success
        assert begun.result_payload["state"] == "ready"
        execution = begun.result_payload["execution"]
        assert execution["operation"] == "baseline_group"
        assert execution["baselines"] == ["fresh-host"]
        assert [case["requirement_id"] for case in execution["cases"]] == expected_ids

        submission = execute_machine_case_contract(execution)
        submitted = handle_baseline_group_submit(
            baseline_group_request(
                int(fresh[0]["id"]),
                function="test_machine.baseline_group.submit",
                payload=submission.payload,
            )
        )
    finally:
        clear_host_control_factory()

    assert submitted.primary_success, submitted.error
    assert submitted.result_payload["requirement_ids"] == expected_ids
    assert submitted.result_payload["baseline_ok"] is True
    assert [
        result["requirement_id"] for result in submitted.result_payload["results"]
    ] == expected_ids
    assert control.case_calls == sum(
        result["case_outcome"] != "blocked_on_precondition"
        for result in submission.payload["results"]
    )
    assert control.full_reset_calls == 1
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM work_claims WHERE released_at IS NULL "
            "AND target_kind = 'qa_admission'"
        ).fetchone()[0]
        == 0
    )


def test_baseline_group_uses_snapshot_order_not_surrogate_id(
    test_db: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = materialize_installer_campaign(test_db, item_id=4210)
    fresh = [row for row in rows if row["host_baseline"] == "fresh-host"]
    configure_test_machine(test_db, tmp_path, monkeypatch)
    for offset, row in enumerate(fresh):
        test_db.execute(
            "UPDATE qa_requirements SET case_position=%s WHERE id=%s",
            (100 - offset, int(row["id"])),
        )
    expected_ids = [int(row["id"]) for row in reversed(fresh)]

    begun = handle_baseline_group_begin(
        baseline_group_request(
            int(fresh[0]["id"]),
            function="test_machine.baseline_group.begin",
        )
    )

    assert begun.primary_success
    execution = begun.result_payload["execution"]
    assert [case["requirement_id"] for case in execution["cases"]] == expected_ids

    aborted = handle_baseline_group_abort(
        baseline_group_request(
            int(fresh[0]["id"]),
            function="test_machine.baseline_group.abort",
            payload={
                "lease_id": execution["lease_id"],
                "contract_digest": execution["contract_digest"],
                "reason": "client_cancelled",
            },
        )
    )
    assert aborted.primary_success


def test_cli_verify_orchestrates_begin_and_submit_over_active_transport(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, Any]] = []
    begin = FunctionCallResponse(
        success=True,
        function="test_machine.verify.begin",
        version="v1",
        result={"execution": {"server": "contract"}},
    )
    final = FunctionCallResponse(
        success=True,
        function="test_machine.verify.submit",
        version="v1",
        result={
            "project": "yoke",
            "status": "verified",
            "checked_at": "now",
            "checks": [],
            "error_code": None,
        },
    )

    def dispatch(**kwargs: Any) -> FunctionCallResponse:
        calls.append(dict(kwargs))
        return begin if len(calls) == 1 else final

    monkeypatch.setattr(test_machine_cli, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(test_machine_cli, "call_dispatcher", dispatch)
    monkeypatch.setattr(
        "yoke_harness.test_machine_verification.execute_verification_contract",
        lambda contract: LocalHostControlSubmission(
            payload={
                "lease_id": 9,
                "contract_digest": "digest",
                "status": "verified",
                "checks": [],
                "error_code": None,
            }
        ),
    )

    exit_code = test_machine_cli.test_machine_verify(
        [
            "--project",
            "yoke",
            "--machine",
            "mac-mini-lab",
            "--json",
        ]
    )

    assert exit_code == 0
    assert [call["function_id"] for call in calls] == [
        "test_machine.verify.begin",
        "test_machine.verify.submit",
    ]
    assert calls[0]["payload"] == {
        "project": "yoke",
        "machine": "mac-mini-lab",
    }
    assert calls[1]["payload"]["contract_digest"] == "digest"
    assert json.loads(capsys.readouterr().out)["function"] == "test_machine.verify"


def test_failed_local_group_baseline_submits_every_case_as_blocked(
    test_db: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = materialize_installer_campaign(test_db, item_id=4202)
    fresh = [row for row in rows if row["host_baseline"] == "fresh-host"]
    configure_test_machine(test_db, tmp_path, monkeypatch)
    control = FakeHostControl(refuse_full_reset=True)
    register_host_control_factory(lambda _material: control)
    try:
        begun = handle_baseline_group_begin(
            baseline_group_request(
                int(fresh[0]["id"]),
                function="test_machine.baseline_group.begin",
            )
        )
        submission = execute_machine_case_contract(
            begun.result_payload["execution"],
        )
        submitted = handle_baseline_group_submit(
            baseline_group_request(
                int(fresh[0]["id"]),
                function="test_machine.baseline_group.submit",
                payload=submission.payload,
            )
        )
    finally:
        clear_host_control_factory()

    assert submitted.primary_success
    assert submitted.result_payload["baseline_ok"] is False
    assert [
        result["requirement_id"] for result in submitted.result_payload["results"]
    ] == [int(row["id"]) for row in fresh]
    assert all(
        result["case_outcome"] == "blocked_on_precondition"
        and result["verdict"] is None
        and result["error_code"] == "test_mac_reset_failed"
        for result in submitted.result_payload["results"]
    )
    assert control.case_calls == 0
    assert control.full_reset_calls == 1
    verification = test_db.execute(
        "SELECT status,error_code,receipt_json FROM test_machine_verifications "
        "WHERE project_id=1"
    ).fetchone()
    assert verification["status"] == "error"
    assert verification["error_code"] == "test_mac_reset_failed"
    receipt = json.loads(verification["receipt_json"])
    assert receipt["checks"][0]["name"] == "fresh-host"
    assert receipt["checks"][0]["ok"] is False
    assert (
        test_db.execute(
            "SELECT verified_at FROM project_capabilities "
            "WHERE project_id=1 AND type=%s",
            (_machine_type("mac-mini-lab"),),
        ).fetchone()["verified_at"]
        is None
    )


def test_baseline_group_begin_ignores_client_membership_and_abort_releases(
    test_db: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = materialize_installer_campaign(test_db, item_id=4205)
    fresh = [row for row in rows if row["host_baseline"] == "fresh-host"]
    anchor_id = int(fresh[0]["id"])
    expected_ids = [int(row["id"]) for row in fresh]
    configure_test_machine(test_db, tmp_path, monkeypatch)
    forged_payload = {
        "host_baseline": "shell-preconfigured",
        "requirement_ids": [anchor_id, 999999],
    }

    direct = handle_baseline_group_execute(
        baseline_group_request(
            anchor_id,
            payload=forged_payload,
        )
    )
    begun = handle_baseline_group_begin(
        baseline_group_request(
            anchor_id,
            function="test_machine.baseline_group.begin",
            payload=forged_payload,
        )
    )

    assert not direct.primary_success
    assert direct.error is not None
    assert direct.error.code == "host_control_client_required"
    assert begun.primary_success
    execution = begun.result_payload["execution"]
    assert execution["baselines"] == ["fresh-host"]
    assert [case["requirement_id"] for case in execution["cases"]] == expected_ids

    aborted = handle_baseline_group_abort(
        baseline_group_request(
            anchor_id,
            function="test_machine.baseline_group.abort",
            payload={
                "lease_id": execution["lease_id"],
                "contract_digest": execution["contract_digest"],
                "reason": "client_cancelled",
            },
        )
    )

    assert aborted.primary_success
    assert aborted.result_payload == {
        "lease_id": execution["lease_id"],
        "released": True,
        "reason": "client_cancelled",
    }
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM work_claims WHERE released_at IS NULL "
            "AND target_kind = 'qa_admission'"
        ).fetchone()[0]
        == 0
    )
