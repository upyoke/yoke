"""Capability-set validation and fail-closed QA case admission."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.machine_config.test_machine import (
    test_machine_capability_type as _machine_type,
)
from yoke_core.domain.qa_case_execution_context import (
    QaCaseExecutionError,
    get_case_execution_context,
)
from yoke_core.domain.qa_method_capabilities import (
    QaMethodCapabilityError,
    capability_kinds,
    encoded_capability_kinds,
)


def test_capability_sets_canonicalize_zero_one_and_many() -> None:
    assert encoded_capability_kinds([]) == "[]"
    assert encoded_capability_kinds(["browser-control"]) == ('["browser-control"]')
    assert capability_kinds(
        '["native-dialog-control", "browser-control", "browser-control"]'
    ) == ("browser-control", "native-dialog-control")


@pytest.mark.parametrize(
    "value",
    ["", "{}", '["browser-control", 3]', '["browser-control", ""]'],
)
def test_invalid_capability_sets_fail_closed(value: str) -> None:
    with pytest.raises(QaMethodCapabilityError):
        capability_kinds(value)


def test_case_admission_names_every_missing_capability() -> None:
    with test_database() as conn:
        item = insert_item(conn, id=2501, project_sequence=2501)
        required = ["browser-control", "desktop-control", "test-machine"]
        row = conn.execute(
            "INSERT INTO qa_requirements("
            "item_id,qa_kind,qa_phase,blocking_mode,requirement_source,"
            "capability_requirements,method_id,method_name,runner_id,"
            "verdict_path,instructions,expected_outcome,method_config,created_at"
            ") VALUES(%s,'plan_case','verification','blocking','flow_derived',"
            "%s,'command','Command','worktree_run','automatic',"
            "'Run the cross-substrate check.','Every check passes.','{}',%s) "
            "RETURNING id",
            (
                int(item["id"]),
                json.dumps(required),
                "2026-08-20T12:00:00Z",
            ),
        ).fetchone()
        requirement_id = int(row["id"])
        conn.execute(
            "INSERT INTO project_capabilities(project_id,type) VALUES(1,%s)",
            (_machine_type("mac-mini-lab"),),
        )
        with pytest.raises(QaCaseExecutionError) as exc_info:
            get_case_execution_context(
                conn,
                requirement_id=requirement_id,
                host_capability_kinds=["browser-control"],
            )
        message = str(exc_info.value)
        assert "desktop-control" in message
        assert "browser-control" not in message
        assert "test-machine" not in message

        context = get_case_execution_context(
            conn,
            requirement_id=requirement_id,
            host_capability_kinds=["browser-control", "desktop-control"],
        )
        assert context["required_capability_kinds"] == required
