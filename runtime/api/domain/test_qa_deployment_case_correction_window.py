"""A run-bound QA case is correctable until it has actually answered.

The defects this window exists for -- a probe asserting a field its
endpoint does not project, a case asserting data that does not exist --
are invisible until the case runs against the real deployed target. Freezing
the row at materialization put them beyond repair the moment they appeared.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.qa_deployment_case_correction_window import (
    correction_window_open,
    determinate_verdict,
)
from yoke_core.domain.qa_method_config_validation import (
    QaMethodConfigError,
    validate_method_config,
)
from yoke_core.domain.qa_requirement_config_update import (
    FROZEN_REQUIREMENT_CODE,
    apply_requirement_update,
)

import pytest


def _run_bound_case(conn: Any, *, run_id: str = "run-correction-window") -> int:
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "created_at) VALUES (%s,1,'flow-correction',%s,'executing',%s)",
        (run_id, "c" * 40, "2026-09-18T00:00:00Z"),
    )
    row = conn.execute(
        "INSERT INTO qa_requirements(deployment_run_id,deployment_stage,qa_kind,"
        "qa_phase,blocking_mode,requirement_source,method_id,plan_case_key,"
        "instructions,expected_outcome,method_config,created_at) "
        "VALUES (%s,'item-qa','plan_case','post_deploy','blocking','flow_derived',"
        "'command','probe','probe the served build','it passes',%s,%s) "
        "RETURNING id",
        (
            run_id,
            json.dumps({"command": "probe --old"}),
            "2026-09-18T00:00:00Z",
        ),
    ).fetchone()
    conn.commit()
    return int(row["id"] if hasattr(row, "keys") else row[0])


def _record_verdict(conn: Any, requirement_id: int, verdict: str) -> None:
    now = "2026-09-18T00:01:00Z"
    conn.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
        "verdict_reason,started_at,completed_at,created_at) "
        "VALUES (%s,'worktree_run','plan_case',%s,'because',%s,%s,%s)",
        (int(requirement_id), verdict, now, now, now),
    )
    conn.commit()


def test_unjudged_run_bound_case_can_be_corrected_in_place(test_db) -> None:
    requirement_id = _run_bound_case(test_db)
    assert correction_window_open(test_db, requirement_id)
    result = apply_requirement_update(
        test_db,
        requirement_id,
        "method_config",
        json.dumps({"command": "probe --corrected"}),
    )
    assert result.ok, result.message
    stored = test_db.execute(
        "SELECT method_config FROM qa_requirements WHERE id=%s", (requirement_id,)
    ).fetchone()
    assert "probe --corrected" in str(stored["method_config"])


@pytest.mark.parametrize("verdict", ["pass", "fail"])
def test_a_determinate_verdict_freezes_the_case(test_db, verdict: str) -> None:
    requirement_id = _run_bound_case(test_db, run_id=f"run-frozen-{verdict}")
    _record_verdict(test_db, requirement_id, verdict)
    assert determinate_verdict(test_db, requirement_id) == verdict
    assert not correction_window_open(test_db, requirement_id)
    result = apply_requirement_update(
        test_db,
        requirement_id,
        "method_config",
        json.dumps({"command": "probe --too-late"}),
    )
    assert not result.ok
    assert result.error_code == FROZEN_REQUIREMENT_CODE
    # The refusal names supersession, the one honest correction left.
    assert "yoke qa requirement supersede" in result.message


@pytest.mark.parametrize("verdict", ["undetermined", "error"])
def test_an_unsettled_verdict_leaves_the_case_correctable(
    test_db, verdict: str
) -> None:
    requirement_id = _run_bound_case(test_db, run_id=f"run-unsettled-{verdict}")
    _record_verdict(test_db, requirement_id, verdict)
    assert determinate_verdict(test_db, requirement_id) == ""
    assert correction_window_open(test_db, requirement_id)


def test_command_reading_base_url_must_declare_it() -> None:
    with pytest.raises(QaMethodConfigError) as excinfo:
        validate_method_config(
            "command",
            {"command": 'probe --base "$BASE_URL"'},
        )
    message = str(excinfo.value)
    assert "requires_base_url" in message
    assert "fallback target" in message

    declared = validate_method_config(
        "command",
        {"command": 'probe --base "$BASE_URL"', "requires_base_url": True},
    )
    assert declared["requires_base_url"] is True


def test_command_not_reading_base_url_is_unaffected() -> None:
    config = validate_method_config("command", {"command": "probe --local"})
    assert config["command"] == "probe --local"
