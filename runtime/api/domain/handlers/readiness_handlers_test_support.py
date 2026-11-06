# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.handlers import claims_path_activation as cpa

from yoke_core.domain.handlers import readiness

_UNPERFORMED_CHECK = {
    "check": "verify_function_owners",
    "reason": "project_checkout_unavailable",
    "recovery": "re-run from a machine with the project checkout registered",
    "retryable": False,
    "context": {"project_id": 7, "project": "some-project"},
}


def _readiness_payload(
    verdict: str,
    classification: str,
    *,
    issues=(),
    unavailable=(),
    advisories=(),
    local_execution_request=None,
) -> dict:
    return {
        "verdict": verdict,
        "classification": classification,
        "issues": list(issues),
        "unavailable_checks": list(unavailable),
        "advisories": list(advisories),
        "local_execution_request": local_execution_request,
    }
