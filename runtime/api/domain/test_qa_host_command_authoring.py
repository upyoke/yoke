"""A Command reaches a Test Machine exactly when it declares os, slots or inherit."""

from __future__ import annotations

from typing import Any

import pytest

from yoke_contracts.qa_case_starting_state import STARTING_STATE_RECOVERY
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    create_plan,
    replace_plan_cases,
)


def _command(key: str, position: int, **fields: Any) -> dict[str, Any]:
    config = fields.pop("config", {})
    return {
        "case_key": key,
        "position": position,
        "method_id": "command",
        "instructions": "Run the host check.",
        "expected_outcome": "The command exits zero.",
        "method_config": {"command": "true", **config},
        **fields,
    }


def _replace(test_db: Any, slug: str, cases: list[dict[str, Any]]) -> list[dict]:
    plan = create_plan(test_db, project="yoke", slug=slug)
    replace_plan_cases(test_db, plan_id=int(plan["id"]), cases=cases)
    return test_db.execute(
        "SELECT case_key, starting_state FROM qa_plan_cases WHERE plan_id=%s",
        (int(plan["id"]),),
    ).fetchall()


def test_os_command_without_a_starting_state_is_refused(test_db: Any) -> None:
    with pytest.raises(QaPlanError) as refused:
        _replace(test_db, "os-no-state", [_command("a", 1, config={"os": "windows"})])
    assert STARTING_STATE_RECOVERY in str(refused.value)


def test_baselines_without_os_are_refused_by_the_authoring_gate(test_db: Any) -> None:
    with pytest.raises(QaPlanError, match="only machine-run cases") as refused:
        _replace(test_db, "no-os", [_command("a", 1, host_baselines=["fresh-host"])])
    assert "method_config.os" in str(refused.value)


def test_inherit_follower_without_os_is_accepted(test_db: Any) -> None:
    cases = _replace(
        test_db,
        "inherit-chain",
        [
            _command("open", 1, config={"os": "windows"}, host_baselines=["fresh-host"]),
            _command("next", 2, starting_state="inherit"),
        ],
    )
    states = {case["case_key"]: case["starting_state"] for case in cases}
    assert states == {"open": "baseline", "next": "inherit"}


def test_follower_declaring_another_os_is_refused(test_db: Any) -> None:
    with pytest.raises(QaPlanError, match="inherited_driver_mismatch"):
        _replace(
            test_db,
            "inherit-other-os",
            [
                _command("open", 1, config={"os": "windows"}, host_baselines=["fresh-host"]),
                _command("next", 2, config={"os": "linux"}, starting_state="inherit"),
            ],
        )


def test_host_control_case_without_os_is_refused(test_db: Any) -> None:
    case = {
        "case_key": "state",
        "position": 1,
        "method_id": "machine-state-check",
        "instructions": "Check host state.",
        "expected_outcome": "State matches.",
        "method_config": {"assertions": [{"argv": ["/usr/bin/true"]}]},
        "host_baselines": ["fresh-host"],
    }
    with pytest.raises(QaPlanError, match="test_machine_platform_undeclared") as refused:
        _replace(test_db, "host-no-os", [case])
    assert "test_machine " not in str(refused.value)
