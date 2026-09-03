"""Per-case fixture lifecycle integration coverage."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from runtime.api.domain.machine_qa_fixture_lifecycle_test_support import (
    FakeExecution,
    FakeFixtureRunner,
    action_result,
    baseline_configs,
    case_contract,
    machine_state_case,
    recipe_config,
    run_lifecycle,
)
from yoke_core.domain import machine_qa_local_execution
from yoke_core.domain.machine_qa_execution import MachineCaseResult
from yoke_core.domain.machine_qa_execution_contract import issue_execution_contract
from yoke_core.domain.machine_qa_method_contracts import (
    MachineQaExecutionError,
    validate_machine_method_config,
)


def test_fixture_lifecycle_wraps_primary_action_in_order() -> None:
    result, execution, events = run_lifecycle()

    assert result.case_outcome == "passed"
    assert execution.execute_calls == 1
    assert events == ["setup", "primary", "post-state", "close"]
    lifecycle = result.evidence["fixture_operations"]
    assert lifecycle["setup"]["outcome"] == "passed"
    assert lifecycle["setup"]["operations"][0]["id"] == "machine.yoke-auth-clear"
    assert lifecycle["post_state"]["outcome"] == "passed"
    assert lifecycle["post_state"]["operations"][0]["outcome"] == "passed"
    assert lifecycle["cleanup_attempts"] == [{"outcome": "passed", "operations": []}]


def test_baseline_configs_normalize_without_selecting_a_variant() -> None:
    normalized = validate_machine_method_config(
        "terminal-check",
        baseline_configs(),
        entry_surface="yoke test",
        required_completion="done",
    )

    variants = normalized["baseline_configs"]
    assert set(variants) == {"fresh-host", "shell-preconfigured"}
    assert variants["fresh-host"]["start_delay"] == 0.0
    assert (
        variants["shell-preconfigured"]["setup_operations"][0]["id"]
        == "machine.path-prepare"
    )


@pytest.mark.parametrize(
    "baseline_configs",
    (
        {"fresh-host": recipe_config()},
        {
            "fresh-host": recipe_config(),
            "shell-preconfigured": recipe_config(),
            "unregistered": recipe_config(),
        },
    ),
)
def test_baseline_configs_require_exact_registered_names(
    baseline_configs: dict[str, Any],
) -> None:
    with pytest.raises(MachineQaExecutionError, match="exactly"):
        validate_machine_method_config(
            "terminal-check",
            {"baseline_configs": baseline_configs},
            entry_surface="yoke test",
            required_completion="done",
        )


def test_fixture_lifecycle_selects_the_case_host_baseline_before_setup() -> None:
    result, execution, events = run_lifecycle(
        case=case_contract(
            method_config=baseline_configs(),
            host_baseline="shell-preconfigured",
        )
    )

    assert result.case_outcome == "passed"
    assert events == ["setup", "primary", "post-state", "close"]
    assert execution.fixture.setup_operations[0][0]["id"] == "machine.path-prepare"
    selected = execution.execute_kwargs[0]["method_config"]
    assert "baseline_configs" not in selected
    assert selected["setup_operations"][0]["id"] == "machine.path-prepare"


def test_failed_baseline_receives_selected_config_without_opening_fixture() -> None:
    blocked = MachineCaseResult(
        case_outcome="blocked_on_precondition",
        verdict="blocked",
        evidence={"case_started": False},
        error_code="baseline_operation_failed",
    )
    result, execution, events = run_lifecycle(
        primary=blocked,
        baseline=SimpleNamespace(ok=False, name="fresh-host"),
        case=case_contract(
            method_config=baseline_configs(),
            host_baseline="fresh-host",
        ),
    )

    assert result == blocked
    assert events == ["primary"]
    assert execution.fixture_create_calls == 0
    selected = execution.execute_kwargs[0]["method_config"]
    assert "baseline_configs" not in selected
    assert selected["setup_operations"][0]["id"] == "machine.yoke-auth-clear"


def test_machine_state_config_defaults_optional_fixture_operations() -> None:
    normalized = validate_machine_method_config(
        "machine-state-check",
        {"assertions": [{"argv": ["/usr/bin/true"]}]},
        entry_surface=None,
        required_completion=None,
    )

    assert normalized == {
        "assertions": [
            {
                "argv": ["/usr/bin/true"],
                "expected_exit": 0,
            }
        ],
        "post_state_assertions": [],
        "setup_operations": [],
    }


def test_machine_state_case_runs_registered_fixture_operations() -> None:
    result, execution, events = run_lifecycle(
        case=machine_state_case(
            {
                "assertions": [{"argv": ["/usr/bin/true"]}],
                "setup_operations": [
                    {
                        "id": "machine.token-file-prepare",
                        "parameters": {
                            "path": "/tmp/yoke-stage.token",
                            "state": "present",
                        },
                    }
                ],
                "post_state_assertions": [
                    {
                        "id": "source-dev.checkout-state-assert",
                        "parameters": {},
                    }
                ],
            }
        )
    )

    assert result.case_outcome == "passed"
    assert events == ["setup", "primary", "post-state", "close"]
    assert (
        execution.fixture.setup_operations[0][0]["id"] == "machine.token-file-prepare"
    )
    assert (
        execution.fixture.post_state_assertions[0][0]["id"]
        == "source-dev.checkout-state-assert"
    )


def test_machine_state_config_rejects_unregistered_fixture_commands() -> None:
    with pytest.raises(MachineQaExecutionError, match="unregistered operation"):
        validate_machine_method_config(
            "machine-state-check",
            {
                "assertions": [{"argv": ["/usr/bin/true"]}],
                "setup_operations": [
                    {
                        "id": "shell.run",
                        "parameters": {"command": "touch /tmp/ambient-state"},
                    }
                ],
            },
            entry_surface=None,
            required_completion=None,
        )


def test_setup_failure_skips_primary_and_post_state_but_cleans_up() -> None:
    result, execution, events = run_lifecycle(
        setup=action_result(False, "machine.yoke-auth-clear")
    )

    assert result.error_code == "fixture_setup_failed"
    assert execution.execute_calls == 0
    assert events == ["setup", "close"]
    assert "primary" not in result.evidence


def test_fixture_failure_preserves_the_reached_baseline_identity() -> None:
    result, _execution, _events = run_lifecycle(
        setup=action_result(False, "machine.yoke-auth-clear"),
        baseline=SimpleNamespace(ok=True, name="fresh-host"),
        case=case_contract(host_baseline="fresh-host"),
    )

    assert result.error_code == "fixture_setup_failed"
    assert result.evidence["baseline"] == "fresh-host"


def test_post_state_failure_discards_primary_evidence() -> None:
    result, execution, events = run_lifecycle(
        post_state=action_result(
            False,
            "source-dev.checkout-state-assert",
        ),
        primary=MachineCaseResult(
            case_outcome="passed",
            verdict="pass",
            evidence={"sensitive-primary-output": "discard-me"},
        ),
    )

    assert result.error_code == "fixture_post_state_failed"
    assert execution.execute_calls == 1
    assert events == ["setup", "primary", "post-state", "close"]
    assert "sensitive-primary-output" not in result.evidence


def test_primary_exception_is_secret_safe_and_cleanup_still_runs() -> None:
    result, execution, events = run_lifecycle(
        primary_error=RuntimeError("private remote output")
    )

    assert result.error_code == "machine_method_failed"
    assert execution.execute_calls == 1
    assert events == ["setup", "primary", "close"]
    assert "private remote output" not in str(result.evidence)
    assert result.evidence["primary_action"] == {"outcome": "failed"}


def test_primary_failed_result_still_runs_post_state_and_cleanup() -> None:
    primary = MachineCaseResult(
        case_outcome="failed",
        verdict="fail",
        evidence={"primary": "safe"},
        error_code="terminal_recipe_assertion_failed",
    )
    result, _execution, events = run_lifecycle(primary=primary)

    assert result.error_code == "terminal_recipe_assertion_failed"
    assert result.case_outcome == "failed"
    assert events == ["setup", "primary", "post-state", "close"]


def test_cleanup_retry_preserves_attempts_and_fails_case_closed() -> None:
    result, _execution, events = run_lifecycle(
        cleanup=[
            action_result(False, "fixture.yoke-api-start"),
            action_result(True, "fixture.yoke-api-start"),
        ]
    )

    assert result.case_outcome == "failed"
    assert result.error_code == "fixture_cleanup_failed"
    assert events == [
        "setup",
        "primary",
        "post-state",
        "close",
        "close",
    ]
    assert result.evidence["fixture_operations"]["cleanup_attempts"] == [
        {
            "outcome": "failed",
            "operations": [{"id": "fixture.yoke-api-start", "outcome": "failed"}],
        },
        {
            "outcome": "passed",
            "operations": [{"id": "fixture.yoke-api-start", "outcome": "passed"}],
        },
    ]


def test_persistent_cleanup_failure_overrides_primary_result() -> None:
    failed_cleanup = action_result(False, "fixture.yoke-api-start")
    result, _execution, events = run_lifecycle(
        cleanup=[failed_cleanup, failed_cleanup],
        primary=MachineCaseResult(
            case_outcome="passed",
            verdict="pass",
            evidence={"primary-private": "discard-me"},
        ),
    )

    assert result.error_code == "fixture_cleanup_failed"
    assert result.case_outcome == "failed"
    assert events[-2:] == ["close", "close"]
    assert "primary-private" not in result.evidence


def test_plan_case_contract_uses_the_same_single_case_lifecycle(
    monkeypatch,
) -> None:
    events: list[str] = []
    fixture = FakeFixtureRunner(events)
    execution = FakeExecution(fixture, events)
    case = case_contract().model_copy(
        update={"case_position": 1, "baseline_position": 1}
    )
    contract = issue_execution_contract(
        operation="plan_case",
        lease_id=1,
        lease_key="QA_HOST:test-mac",
        project_id=1,
        project="yoke",
        settings={
            "resource_name": "test-mac",
            "host": "test-mac.example",
            "user": "tester",
            "host_kind": "mac-ssh",
            "operating_notes": "",
        },
        cases=[case.model_dump(mode="json")],
        plan_execution_id="plan-run-1",
        roster_digest="a" * 64,
        ordinal=0,
        case_position=1,
        baseline_position=1,
    )
    monkeypatch.setattr(
        machine_qa_local_execution,
        "_execution",
        lambda _contract: execution,
    )

    submission = machine_qa_local_execution.execute_machine_case_contract(
        contract.model_dump(mode="json")
    )

    assert submission.payload["results"][0]["case_outcome"] == "passed"
    assert "baseline_ok" not in submission.payload
    assert events == ["setup", "primary", "post-state", "close"]
