"""Reusable doubles and contracts for fixture-lifecycle tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from yoke_core.domain.host_control_executor import HostActionResult
from yoke_core.domain.machine_qa_execution import MachineCaseResult
from yoke_core.domain.machine_qa_execution_contract import MachineQaCaseContract
from yoke_core.domain.machine_qa_fixture_lifecycle import (
    execute_case_with_fixture_lifecycle,
)


def action_result(
    ok: bool,
    operation_id: str,
    *,
    outcome: str | None = None,
) -> HostActionResult:
    return HostActionResult(
        ok=ok,
        evidence={
            "operations": [
                {
                    "id": operation_id,
                    "outcome": outcome or ("passed" if ok else "failed"),
                }
            ]
        },
        error_code=None if ok else "fixture_operation_failed",
    )


class FakeFixtureExecutor:
    def __init__(
        self,
        events: list[str],
        *,
        setup: HostActionResult | None = None,
        post_state: HostActionResult | None = None,
        cleanup: list[HostActionResult] | None = None,
    ) -> None:
        self.events = events
        self.setup_result = setup or action_result(
            True,
            "machine.yoke-auth-clear",
        )
        self.post_result = post_state or action_result(
            True,
            "source-dev.checkout-state-assert",
        )
        self.setup_operations: list[list[dict[str, Any]]] = []
        self.post_state_assertions: list[list[dict[str, Any]]] = []
        self.cleanup_results = list(
            cleanup
            or [
                HostActionResult(
                    True,
                    {"operations": []},
                )
            ]
        )

    def execute_setup_operations(self, operations):
        self.events.append("setup")
        self.setup_operations.append(list(operations))
        return self.setup_result

    def execute_post_state_assertions(self, operations):
        self.events.append("post-state")
        self.post_state_assertions.append(list(operations))
        return self.post_result

    def close(self):
        self.events.append("close")
        return self.cleanup_results.pop(0)


class FakeExecution:
    baseline = None

    def __init__(
        self,
        fixture: FakeFixtureExecutor,
        events: list[str],
        *,
        primary: MachineCaseResult | None = None,
        primary_error: Exception | None = None,
        baseline: Any = None,
    ) -> None:
        self.fixture = fixture
        self.fixture_create_calls = 0
        self.control = SimpleNamespace(
            create_fixture_operation_executor=self._create_fixture_operation_executor
        )
        self.material = SimpleNamespace(
            settings={"resource_name": "test-mac"},
            secrets={},
        )
        self.events = events
        self.baseline = baseline
        self.primary = primary or MachineCaseResult(
            case_outcome="passed",
            verdict="pass",
            evidence={"primary": "safe"},
        )
        self.primary_error = primary_error
        self.execute_calls = 0
        self.execute_kwargs: list[dict[str, Any]] = []

    def _create_fixture_operation_executor(self) -> FakeFixtureExecutor:
        self.fixture_create_calls += 1
        return self.fixture

    def execute(self, **kwargs: Any) -> MachineCaseResult:
        self.events.append("primary")
        self.execute_calls += 1
        self.execute_kwargs.append(kwargs)
        if self.primary_error is not None:
            raise self.primary_error
        return self.primary


def recipe_config(
    *,
    setup_operation_id: str = "machine.yoke-auth-clear",
) -> dict[str, Any]:
    return {
        "actions": [
            {
                "step": "done",
                "keys": [],
                "capture": False,
            }
        ],
        "capture_checkpoints": [],
        "execution_mode": "ssh-command",
        "expected_return_codes": [0],
        "expected_text": ["done"],
        "max_wall_seconds": 60,
        "notes": "fixture lifecycle test",
        "post_checks": ["secret_free"],
        "post_state_assertions": [
            {
                "id": "source-dev.checkout-state-assert",
                "parameters": {},
            }
        ],
        "setup_operations": [
            {
                "id": setup_operation_id,
                "parameters": {},
            }
        ],
        "stage_files": [],
        "start_delay": 0,
        "step_delay": 0,
    }


def baseline_configs() -> dict[str, Any]:
    return {
        "baseline_configs": {
            "fresh-host": recipe_config(),
            "shell-preconfigured": recipe_config(
                setup_operation_id="machine.path-prepare"
            ),
        }
    }


def case_contract(
    *,
    method_config: dict[str, Any] | None = None,
    host_baseline: str | None = None,
) -> MachineQaCaseContract:
    return MachineQaCaseContract.model_validate(
        {
            "requirement_id": 1,
            "item_id": 1,
            "plan_id": None,
            "case_key": "fixture-lifecycle",
            "method_id": "terminal-check",
            "method_name": "Terminal check",
            "executor_id": "host_control",
            "required_capability_kind": "test-machine",
            "verdict_path": "automated",
            "qa_kind": "acceptance",
            "instructions": "Run the typed recipe.",
            "expected_outcome": "The recipe completes.",
            "method_config": method_config or recipe_config(),
            "host_baseline": host_baseline,
            "entry_surface": "yoke test",
            "required_completion": "done",
            "workflow_transition_id": None,
            "project_id": 1,
            "project": "yoke",
            "lane_branch": None,
        }
    )


def machine_state_case(
    method_config: dict[str, Any],
) -> MachineQaCaseContract:
    return case_contract(method_config=method_config).model_copy(
        update={
            "method_id": "machine-state-check",
            "method_name": "Machine state check",
            "entry_surface": None,
            "required_completion": None,
        }
    )


def run_lifecycle(
    *,
    setup: HostActionResult | None = None,
    post_state: HostActionResult | None = None,
    cleanup: list[HostActionResult] | None = None,
    primary: MachineCaseResult | None = None,
    primary_error: Exception | None = None,
    baseline: Any = None,
    case: MachineQaCaseContract | None = None,
):
    events: list[str] = []
    fixture = FakeFixtureExecutor(
        events,
        setup=setup,
        post_state=post_state,
        cleanup=cleanup,
    )
    execution = FakeExecution(
        fixture,
        events,
        primary=primary,
        primary_error=primary_error,
        baseline=baseline,
    )
    result = execute_case_with_fixture_lifecycle(
        execution,
        case or case_contract(),
    )
    return result, execution, events


__all__ = [
    "FakeExecution",
    "FakeFixtureExecutor",
    "action_result",
    "baseline_configs",
    "case_contract",
    "machine_state_case",
    "recipe_config",
    "run_lifecycle",
]
