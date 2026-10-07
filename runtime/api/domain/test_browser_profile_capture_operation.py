"""Profile capture shares host authority while preserving the clean golden."""

import json
import hashlib

import pytest

from runtime.api.domain.machine_operation_test_support import (
    operation_request,
    run_operation,
    MACHINE,
)
from runtime.api.domain.machine_qa_host_test_support import (
    TEST_MACHINE_SETTINGS,
    configure_test_machine,
)
from runtime.api.domain.machine_qa_test_support import (
    FakeHostControl,
    make_conn,
    GOLDEN_BASELINE_PATH,
)
from yoke_core.domain.handlers.machine_qa_operation import (
    handle_operation_begin,
    handle_operation_submit,
)
from yoke_contracts.machine_qa_execution import issue_execution_contract
from yoke_core.domain.machine_qa_capability import test_machine_detail as machine_detail
from yoke_core.domain.machine_qa_fixture_operations import (
    MachineQaFixtureOperationRunner,
)
from yoke_core.domain.machine_qa_fixture_validation import (
    validate_setup_operations,
    MachineQaFixtureOperationError,
)
from yoke_harness.test_machine_types import HostActionResult


def declare_linux(conn):
    settings = {
        **TEST_MACHINE_SETTINGS,
        "os": "linux",
        "golden_baseline_path": GOLDEN_BASELINE_PATH,
    }
    conn.execute(
        "UPDATE project_capabilities SET settings=? WHERE type LIKE ?",
        (json.dumps(settings), "test-machine:%"),
    )
    conn.commit()


def test_profile_capture_records_separate_path_and_retains_home_golden(
    tmp_path, monkeypatch
):
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)
    declare_linux(conn)

    def capture(contract, _control):
        return HostActionResult(
            True,
            {
                "capture_component": "browser-profile",
                "sealed": True,
                "browser_profile_baseline_path": contract.golden_destination,
                "manifest_digest": "a" * 64,
            },
        )

    monkeypatch.setattr(
        "yoke_harness.ssh_browser_profile_capture.capture_browser_profile", capture
    )
    submitted, execution = run_operation(
        "golden_capture",
        control=FakeHostControl(),
        begin_payload={"capture_component": "browser-profile"},
    )
    assert submitted.primary_success, submitted.error
    assert execution["capture_component"] == "browser-profile"
    destination = execution["golden_destination"]
    assert destination != GOLDEN_BASELINE_PATH
    settings = machine_detail(conn, project="yoke", machine=MACHINE)["settings"]
    assert settings["golden_baseline_path"] == GOLDEN_BASELINE_PATH
    assert settings["browser_profile_baseline_path"] == destination
    assert submitted.result_payload["browser_profile_baseline_path"] == destination
    replay = {
        "project": "yoke",
        "lease_id": execution["lease_id"],
        "contract_digest": execution["contract_digest"],
        "operation": "golden_capture",
        "capture_component": "browser-profile",
        "destination": destination,
        "status": "verified",
        "checks": submitted.result_payload["checks"],
        "error_code": None,
    }
    later = destination + "-later"
    conn.execute(
        "UPDATE project_capabilities SET settings=? WHERE type LIKE ?",
        (
            json.dumps({**settings, "browser_profile_baseline_path": later}),
            "test-machine:%",
        ),
    )
    conn.commit()
    accepted = handle_operation_submit(operation_request(replay))
    assert accepted.primary_success, accepted.error
    assert (
        machine_detail(conn, project="yoke", machine=MACHINE)["settings"][
            "browser_profile_baseline_path"
        ]
        == later
    )
    forged = json.loads(json.dumps(replay))
    forged["destination"] = destination + "-forged"
    forged["checks"][0]["browser_profile_baseline_path"] = forged["destination"]
    assert not handle_operation_submit(operation_request(forged)).primary_success
    downgraded = {**replay, "capture_component": None}
    assert not handle_operation_submit(operation_request(downgraded)).primary_success


def test_profile_capture_failure_leaves_baseline_settings_unchanged(
    tmp_path, monkeypatch
):
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)
    declare_linux(conn)
    monkeypatch.setattr(
        "yoke_harness.ssh_browser_profile_capture.capture_browser_profile",
        lambda *_: HostActionResult(False, {}, "browser_profile_writer_active"),
    )
    submitted, _ = run_operation(
        "golden_capture",
        control=FakeHostControl(),
        begin_payload={"capture_component": "browser-profile"},
    )
    assert submitted.primary_success
    assert submitted.result_payload["status"] == "error"
    settings = machine_detail(conn, project="yoke", machine=MACHINE)["settings"]
    assert settings["golden_baseline_path"] == GOLDEN_BASELINE_PATH
    assert "browser_profile_baseline_path" not in settings


def test_capture_destination_cannot_target_the_home_golden(tmp_path, monkeypatch):
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)
    declare_linux(conn)
    begun = handle_operation_begin(
        operation_request(
            {
                "project": "yoke",
                "operation": "golden_capture",
                "capture_component": "browser-profile",
                "destination": GOLDEN_BASELINE_PATH,
            }
        )
    )
    assert not begun.primary_success


def test_profile_fixture_is_explicit_and_uses_installed_interpreter():
    calls = []

    class Result:
        returncode = 0

    def run(command, **_):
        calls.append(command)
        return Result()

    runner = MachineQaFixtureOperationRunner(
        run_remote=run,
        upload_text=lambda *_: None,
        home="/home/testuser",
        execution_shell="/bin/bash",
    )
    result = runner.execute_setup_operations(
        [
            {
                "id": "machine.browser-profile-restore",
                "parameters": {
                    "project": "yoke",
                    "baseline_path": "/var/lib/goldens/profile",
                },
            }
        ]
    )
    assert result.ok
    assert len(calls) == 1
    assert "yoke_harness.browser_profile_archive" in calls[0]
    assert "shebang" in calls[0]
    assert "/home/testuser/.local/bin/yoke" in calls[0]
    assert ".yoke/secrets/capability-secrets/yoke/browser-control/profile" in calls[0]
    assert runner.close().ok


@pytest.mark.parametrize(
    "parameters",
    [
        {"project": "../other", "baseline_path": "/var/lib/goldens/profile"},
        {"project": "yoke", "baseline_path": "~/profile"},
        {
            "project": "yoke",
            "baseline_path": "/var/lib/goldens/profile",
            "command": "anything",
        },
    ],
)
def test_profile_fixture_rejects_unsafe_or_open_parameters(parameters):
    with pytest.raises(MachineQaFixtureOperationError):
        validate_setup_operations(
            [{"id": "machine.browser-profile-restore", "parameters": parameters}]
        )


def test_home_capture_preserves_existing_wire_shape_and_digest():
    contract = issue_execution_contract(
        operation="golden_capture",
        lease_id=1,
        lease_key="test-host",
        project_id=1,
        project="yoke",
        settings=TEST_MACHINE_SETTINGS,
        golden_destination=GOLDEN_BASELINE_PATH,
    )
    document = contract.model_dump(mode="json")
    assert "capture_component" not in document
    payload = {
        key: value
        for key, value in document.items()
        if key not in {"contract_digest", "selection_reason"}
    }
    assert (
        hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        == contract.contract_digest
    )
