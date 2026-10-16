"""A QA case targets stage only with a declared reason production cannot prove it."""

import json

import pytest

from yoke_core.domain.qa_plan_detail import get_plan
from yoke_core.domain.qa_plan_edit import _current_cases
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    create_plan,
    replace_plan_cases,
)

CASE = {
    "case_key": "stage-proof",
    "method_id": "command",
    "instructions": "Run the command against the case target.",
    "expected_outcome": "The target answers successfully.",
    "method_config": {"command": "true"},
}


def _environment(conn, name, *, production):
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,settings,created_at) "
        "SELECT id,1,%s,%s,%s,'2026-10-14T00:00:00Z' FROM sites "
        "WHERE project_id=1 ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO UPDATE SET settings=EXCLUDED.settings",
        (
            name,
            f"https://{name}.example.test",
            json.dumps({"role": {"production": production}}),
        ),
    )


def _plan(conn):
    _environment(conn, "stage", production=False)
    _environment(conn, "prod", production=True)
    return create_plan(
        conn, project="yoke", slug="stage-reasons", target_environment="prod"
    )


def test_stage_target_without_reason_refuses_with_recovery(test_db):
    plan = _plan(test_db)
    with pytest.raises(QaPlanError) as refused:
        replace_plan_cases(
            test_db,
            plan_id=plan["id"],
            cases=[{**CASE, "target_envs": ["stage", "prod"]}],
        )
    message = str(refused.value)
    assert "stage_reason_required" in message
    assert "'stage'" in message and "'prod'" not in message
    assert "creates_or_destroys_data or changes_infrastructure" in message


@pytest.mark.parametrize(
    "reason", ["creates_or_destroys_data", "changes_infrastructure"]
)
def test_stage_target_with_valid_reason_saves_and_reads_back(test_db, reason):
    plan = _plan(test_db)
    replace_plan_cases(
        test_db,
        plan_id=plan["id"],
        cases=[{**CASE, "target_envs": ["stage"], "stage_reason": reason}],
    )
    assert _current_cases(test_db, plan["id"])[0]["stage_reason"] == reason
    assert get_plan(test_db, plan_id=plan["id"])["cases"][0]["stage_reason"] == reason


def test_production_and_default_targets_need_no_reason(test_db):
    plan = _plan(test_db)
    replace_plan_cases(
        test_db,
        plan_id=plan["id"],
        cases=[
            {**CASE, "target_envs": ["prod"]},
            {**CASE, "case_key": "default-target", "target_envs": []},
        ],
    )
    assert [case["stage_reason"] for case in _current_cases(test_db, plan["id"])] == [
        None,
        None,
    ]


def test_undeclared_environment_counts_as_stage(test_db):
    plan = _plan(test_db)
    _environment(test_db, "preview", production=None)
    with pytest.raises(QaPlanError, match="stage_reason_required"):
        replace_plan_cases(
            test_db,
            plan_id=plan["id"],
            cases=[{**CASE, "target_envs": ["preview"]}],
        )


@pytest.mark.parametrize(
    ("target_envs", "reason", "code"),
    [
        (["stage"], "read_only_smoke", "stage_reason_invalid"),
        (["prod"], "changes_infrastructure", "stage_reason_without_stage_target"),
        ([], "creates_or_destroys_data", "stage_reason_without_stage_target"),
    ],
)
def test_invalid_or_unneeded_reason_refuses(test_db, target_envs, reason, code):
    plan = _plan(test_db)
    with pytest.raises(QaPlanError, match=code):
        replace_plan_cases(
            test_db,
            plan_id=plan["id"],
            cases=[{**CASE, "target_envs": target_envs, "stage_reason": reason}],
        )
