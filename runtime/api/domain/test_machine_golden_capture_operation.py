"""What a golden capture writes, records, and refuses to guess."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.domain.machine_operation_test_support import (
    MACHINE,
    operation_request,
    run_operation,
)
from runtime.api.domain.machine_qa_baseline_group_test_support import (
    TEST_MACHINE_SETTINGS,
    configure_test_machine,
)
from runtime.api.domain.machine_qa_test_support import (
    GOLDEN_BASELINE_PATH,
    FakeHostControl,
    make_conn,
)
from yoke_contracts.machine_config.test_machine import (
    validate_test_machine_settings,
)
from yoke_core.domain.handlers.machine_qa_operation import handle_operation_begin
from yoke_core.domain.machine_qa_capability import (
    test_machine_detail as machine_detail,
)


def _declare_golden_baseline(conn) -> None:
    conn.execute(
        "UPDATE project_capabilities SET settings=? WHERE type LIKE ?",
        (
            json.dumps(
                validate_test_machine_settings(
                    {
                        **TEST_MACHINE_SETTINGS,
                        "golden_baseline_path": GOLDEN_BASELINE_PATH,
                    }
                ),
                separators=(",", ":"),
                sort_keys=True,
            ),
            "test-machine:%",
        ),
    )
    conn.commit()


def test_capture_records_the_baseline_it_just_produced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)
    _declare_golden_baseline(conn)
    control = FakeHostControl()

    submitted, execution = run_operation("golden_capture", control=control)

    assert submitted.primary_success, submitted.error
    destination = execution["golden_destination"]
    # A capture never overwrites the baseline it was taken beside: a failed
    # one would leave the machine with no baseline at all.
    assert destination != GOLDEN_BASELINE_PATH
    assert destination.startswith("/Users/Shared/yoke-golden/")
    assert control.captured_destinations == [destination]
    assert submitted.result_payload["golden_baseline_path"] == destination
    detail = machine_detail(conn, project="yoke", machine=MACHINE)
    assert detail["settings"]["golden_baseline_path"] == destination
    [receipt] = detail["operations"]
    assert receipt["operation"] == "golden_capture"
    assert receipt["checks"][0]["manifest_digest"]


def test_capture_refuses_when_there_is_nowhere_to_put_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The fixture machine declares no golden baseline, so there is no
    # directory to capture beside and nothing to guess from.
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)

    begun = handle_operation_begin(
        operation_request({"project": "yoke", "operation": "golden_capture"})
    )

    assert not begun.primary_success
    assert "declares no golden_baseline_path" in begun.error.message
    assert "--destination" in begun.error.message


def test_a_refused_capture_leaves_the_declared_baseline_alone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)
    control = FakeHostControl(refuse_capture="golden_capture_yoke_residue")

    submitted, execution = run_operation(
        "golden_capture",
        control=control,
        begin_payload={"destination": "/Users/Shared/yoke-golden/tester-home-new"},
    )

    assert submitted.primary_success, submitted.error
    assert submitted.result_payload["status"] == "error"
    assert submitted.result_payload["error_code"] == "golden_capture_yoke_residue"
    assert submitted.result_payload["golden_baseline_path"] is None
    detail = machine_detail(conn, project="yoke", machine=MACHINE)
    assert "golden_baseline_path" not in detail["settings"]
    [receipt] = detail["operations"]
    assert receipt["checks"][0]["refusal"]["reason"] == "yoke_residue"
    assert receipt["checks"][0]["refusal"]["recovery"]
    assert execution["golden_destination"] == (
        "/Users/Shared/yoke-golden/tester-home-new"
    )
