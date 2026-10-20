"""Closed validation for the Machine QA machine-admission fixture operations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.machine_qa_admission_host import MODE_PORTS, api_url
from yoke_core.domain.machine_qa_admission_state import EXPECTATIONS
from yoke_core.domain.machine_qa_fixture_validation_common import (
    Validator,
    operation_error,
)

PREPARE = "fixture.machine-admission-prepare"
STATE_ASSERT = "fixture.machine-admission-state-assert"


def _mode(operation_id: str, parameters: Mapping[str, Any]) -> str:
    mode = parameters.get("mode")
    if mode not in MODE_PORTS:
        raise operation_error(operation_id, f"mode must be one of {sorted(MODE_PORTS)}")
    return str(mode)


def _validate_prepare(parameters: Mapping[str, Any]) -> dict[str, Any]:
    if set(parameters) != {"mode"}:
        raise operation_error(PREPARE, "parameters must be exactly mode")
    return {"mode": _mode(PREPARE, parameters)}


def _validate_state_assert(parameters: Mapping[str, Any]) -> dict[str, Any]:
    if set(parameters) != {"mode", "expect"}:
        raise operation_error(
            STATE_ASSERT, "parameters must be exactly mode and expect"
        )
    mode = _mode(STATE_ASSERT, parameters)
    if parameters["expect"] not in EXPECTATIONS[mode]:
        raise operation_error(
            STATE_ASSERT,
            f"expect must be one of {sorted(EXPECTATIONS[mode])} for {mode}",
        )
    return {"mode": mode, "expect": str(parameters["expect"])}


ADMISSION_SETUP_VALIDATORS: dict[str, Validator] = {PREPARE: _validate_prepare}
ADMISSION_POST_VALIDATORS: dict[str, Validator] = {STATE_ASSERT: _validate_state_assert}


def admission_operator_urls(config: Mapping[str, Any]) -> tuple[str, ...]:
    """The loopback servers a recipe's admission fixture serves for approval.

    A browser approval gate may approve only on a declared origin; a case that
    prepares an admission server declares that server's origin this way.
    """
    return tuple(
        api_url(str(row["parameters"]["mode"]))
        for row in config.get("setup_operations") or ()
        if row.get("id") == PREPARE
        and MODE_PORTS.get(str(row["parameters"]["mode"])) is not None
    )


__all__ = [
    "admission_operator_urls",
    "ADMISSION_POST_VALIDATORS",
    "ADMISSION_SETUP_VALIDATORS",
    "PREPARE",
    "STATE_ASSERT",
]
