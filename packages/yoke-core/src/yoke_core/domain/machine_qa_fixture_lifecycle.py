"""Per-case Machine QA fixture setup, assertion, and cleanup lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from yoke_core.domain.host_control_runner import HostActionResult
from yoke_core.domain.machine_qa_execution import (
    MachineCaseResult,
    MachineQaLease,
)
from yoke_core.domain.machine_qa_execution_contract import (
    MachineQaCaseContract,
)
from yoke_core.domain.machine_qa_fixture_operations import (
    MachineQaFixtureOperationRunner,
)
from yoke_core.domain.machine_qa_method_contracts import (
    validate_machine_method_config,
)


_MAX_CLEANUP_ATTEMPTS = 2


def _empty_result(*, ok: bool, error_code: str | None = None) -> HostActionResult:
    return HostActionResult(
        ok=ok,
        evidence={"operations": []},
        error_code=error_code,
    )


def _operation_outcomes(result: HostActionResult) -> list[dict[str, str]]:
    """Project runner evidence to operation identifiers and outcomes only."""
    raw = result.evidence.get("operations")
    if not isinstance(raw, list):
        return []
    outcomes: list[dict[str, str]] = []
    for row in raw:
        if not isinstance(row, Mapping):
            continue
        operation_id = str(row.get("id") or "")
        outcome = str(row.get("outcome") or "")
        if operation_id and outcome in {"passed", "failed"}:
            outcomes.append({"id": operation_id, "outcome": outcome})
    return outcomes


def _close_with_retry(
    fixture: MachineQaFixtureOperationRunner,
) -> list[HostActionResult]:
    attempts = []
    for _attempt in range(_MAX_CLEANUP_ATTEMPTS):
        try:
            result = fixture.close()
        except Exception:
            result = _empty_result(
                ok=False,
                error_code="fixture_cleanup_failed",
            )
        attempts.append(result)
        if result.ok:
            break
    return attempts


def _lifecycle_evidence(
    *,
    setup: HostActionResult,
    post_state: HostActionResult,
    cleanup_attempts: list[HostActionResult],
) -> dict[str, Any]:
    return {
        "setup": {
            "outcome": "passed" if setup.ok else "failed",
            "operations": _operation_outcomes(setup),
        },
        "post_state": {
            "outcome": "passed" if post_state.ok else "failed",
            "operations": _operation_outcomes(post_state),
        },
        "cleanup_attempts": [
            {
                "outcome": "passed" if attempt.ok else "failed",
                "operations": _operation_outcomes(attempt),
            }
            for attempt in cleanup_attempts
        ],
    }


def _failed_case(
    execution: MachineQaLease,
    case: MachineQaCaseContract,
    *,
    error_code: str,
    lifecycle: Mapping[str, Any],
    primary_failed: bool = False,
) -> MachineCaseResult:
    evidence: dict[str, Any] = {
        "runner_id": "host_control",
        "machine": execution.material.settings["resource_name"],
        "method_id": case.method_id,
        "baseline": execution.baseline.name if execution.baseline else None,
        "fixture_operations": dict(lifecycle),
    }
    if primary_failed:
        evidence["primary_action"] = {"outcome": "failed"}
    return MachineCaseResult(
        case_outcome="failed",
        verdict="fail",
        evidence=evidence,
        error_code=error_code,
    )


def execute_case_with_fixture_lifecycle(
    execution: MachineQaLease,
    case: MachineQaCaseContract,
) -> MachineCaseResult:
    """Run one executable case inside its own closed fixture lifecycle."""
    config = validate_machine_method_config(
        case.method_id,
        case.method_config,
        entry_surface=case.entry_surface,
        required_completion=case.required_completion,
        host_baseline=case.host_baseline,
    )
    if execution.baseline is not None and not execution.baseline.ok:
        return execution.execute(
            method_id=case.method_id,
            method_config=config,
            entry_surface=case.entry_surface,
            required_completion=case.required_completion,
        )
    if isinstance(config.get("execution_blocker"), Mapping):
        return execution.execute(
            method_id=case.method_id,
            method_config=config,
            entry_surface=case.entry_surface,
            required_completion=case.required_completion,
        )

    try:
        fixture = execution.control.create_fixture_operation_runner()
    except Exception:
        lifecycle = {
            "setup": {"outcome": "failed", "operations": []},
            "post_state": {"outcome": "failed", "operations": []},
            "cleanup_attempts": [],
        }
        return _failed_case(
            execution,
            case,
            error_code="fixture_runner_unavailable",
            lifecycle=lifecycle,
        )

    setup = _empty_result(ok=True)
    post_state = _empty_result(ok=True)
    cleanup_attempts: list[HostActionResult] = []
    primary: MachineCaseResult | None = None
    primary_failed = False
    try:
        try:
            setup = fixture.execute_setup_operations(config.get("setup_operations", []))
        except Exception:
            setup = _empty_result(
                ok=False,
                error_code="fixture_setup_failed",
            )
        if setup.ok:
            try:
                primary = execution.execute(
                    method_id=case.method_id,
                    method_config=config,
                    entry_surface=case.entry_surface,
                    required_completion=case.required_completion,
                )
            except Exception:
                primary_failed = True
            if not primary_failed:
                try:
                    post_state = fixture.execute_post_state_assertions(
                        config.get("post_state_assertions", [])
                    )
                except Exception:
                    post_state = _empty_result(
                        ok=False,
                        error_code="fixture_post_state_failed",
                    )
    finally:
        cleanup_attempts = _close_with_retry(fixture)

    lifecycle = _lifecycle_evidence(
        setup=setup,
        post_state=post_state,
        cleanup_attempts=cleanup_attempts,
    )
    cleanup_ok = bool(cleanup_attempts) and all(
        attempt.ok for attempt in cleanup_attempts
    )
    if not cleanup_ok:
        return _failed_case(
            execution,
            case,
            error_code="fixture_cleanup_failed",
            lifecycle=lifecycle,
            primary_failed=primary_failed,
        )
    if not setup.ok:
        return _failed_case(
            execution,
            case,
            error_code="fixture_setup_failed",
            lifecycle=lifecycle,
        )
    if not post_state.ok:
        return _failed_case(
            execution,
            case,
            error_code="fixture_post_state_failed",
            lifecycle=lifecycle,
        )
    if primary_failed or primary is None:
        return _failed_case(
            execution,
            case,
            error_code="machine_method_failed",
            lifecycle=lifecycle,
            primary_failed=True,
        )
    return replace(
        primary,
        evidence={
            **primary.evidence,
            "fixture_operations": lifecycle,
        },
    )


__all__ = ["execute_case_with_fixture_lifecycle"]
