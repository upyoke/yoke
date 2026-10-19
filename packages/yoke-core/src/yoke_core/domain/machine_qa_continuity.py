"""Continuity preconditions produce an unstarted case result, before setup."""

from typing import Any

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_harness.qa_continuity_fingerprint import check_continuity
from yoke_core.domain.machine_qa_case_result import MachineCaseResult


def continuity_failure(execution: Any, case: Any) -> Any:
    if "continuity_fingerprint" not in case.method_config:
        return None
    try:
        check_continuity(execution.control, case.method_config)
    except HostControlLocalError as exc:
        return MachineCaseResult(
            case_outcome="blocked_on_precondition",
            verdict="blocked",
            error_code=exc.code,
            evidence={
                "case_started": False,
                "continuity_fingerprint": {
                    "ok": False,
                    "reason": str(exc),
                    "recovery": exc.recovery_hint,
                },
            },
        )
    return None
