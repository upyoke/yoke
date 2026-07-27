"""Bounded case-input contracts for the three Machine QA methods."""

from __future__ import annotations

from typing import Any, Mapping


MACHINE_METHODS = frozenset({
    "terminal-check",
    "terminal-inspection",
    "machine-state-check",
})
_MAX_STEPS = 100
_MAX_ASSERTIONS = 50


class MachineQaExecutionError(ValueError):
    """A case cannot execute through the registered Machine QA contract."""


def validate_machine_method_config(
    method_id: str,
    config: Mapping[str, Any],
    *,
    entry_surface: str | None,
    required_completion: str | None,
) -> dict[str, Any]:
    """Validate bounded structured case input; shell strings are never accepted."""
    if method_id not in MACHINE_METHODS:
        raise MachineQaExecutionError(f"unknown Machine QA method {method_id!r}")
    if not isinstance(config, Mapping):
        raise MachineQaExecutionError("method_config must be an object")
    if method_id in {"terminal-check", "terminal-inspection"}:
        _require_keys(
            config,
            {"steps", "capture_checkpoints"},
            required={"steps"},
        )
        if (
            not str(entry_surface or "").strip()
            or len(str(entry_surface)) > 2000
        ):
            raise MachineQaExecutionError("Terminal cases require entry_surface")
        if not str(required_completion or "").strip():
            raise MachineQaExecutionError(
                "Terminal cases require required_completion"
            )
        steps = config.get("steps")
        if not isinstance(steps, list) or not 1 <= len(steps) <= _MAX_STEPS:
            raise MachineQaExecutionError("Terminal cases require 1..100 steps")
        normalized_steps = [
            _terminal_step(row, index)
            for index, row in enumerate(steps, start=1)
        ]
        keys = [row["key"] for row in normalized_steps]
        if len(keys) != len(set(keys)):
            raise MachineQaExecutionError("Terminal step keys must be unique")
        if str(required_completion) not in keys:
            raise MachineQaExecutionError(
                "required_completion must name a Terminal step key"
            )
        checkpoints = config.get("capture_checkpoints") or []
        if not isinstance(checkpoints, list) or any(
            not isinstance(value, str) or not value.strip()
            for value in checkpoints
        ):
            raise MachineQaExecutionError(
                "capture_checkpoints must be non-empty strings"
            )
        unknown_checkpoints = sorted(set(checkpoints) - set(keys))
        if unknown_checkpoints:
            raise MachineQaExecutionError(
                "capture_checkpoints name unknown step keys: "
                + ", ".join(unknown_checkpoints)
            )
        return {
            "steps": normalized_steps,
            "capture_checkpoints": list(dict.fromkeys(checkpoints)),
        }
    _require_keys(config, {"assertions"}, required={"assertions"})
    assertions = config.get("assertions")
    if (
        not isinstance(assertions, list)
        or not 1 <= len(assertions) <= _MAX_ASSERTIONS
    ):
        raise MachineQaExecutionError(
            "Machine state cases require 1..50 assertions"
        )
    return {"assertions": [_assertion(row) for row in assertions]}


def _require_keys(
    config: Mapping[str, Any],
    allowed: set[str],
    *,
    required: set[str],
) -> None:
    unknown = sorted(set(config) - allowed)
    missing = sorted(required - set(config))
    if unknown or missing:
        raise MachineQaExecutionError(
            f"invalid method_config keys; missing={missing}, unknown={unknown}"
        )


def _terminal_step(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise MachineQaExecutionError("Terminal steps must be objects")
    _require_keys(
        raw,
        {"key", "send", "expect", "timeout_seconds"},
        required={"expect"},
    )
    key = str(raw.get("key") or f"step-{index}").strip()
    expect = str(raw.get("expect") or "")
    send = str(raw.get("send") or "")
    timeout = raw.get("timeout_seconds", 30)
    if (
        not key
        or len(key) > 80
        or not expect
        or len(expect) > 2000
        or len(send) > 2000
    ):
        raise MachineQaExecutionError("Terminal step text is empty or too long")
    if not isinstance(timeout, int) or not 1 <= timeout <= 300:
        raise MachineQaExecutionError(
            "Terminal timeout_seconds must be 1..300"
        )
    return {
        "key": key,
        "send": send,
        "expect": expect,
        "timeout_seconds": timeout,
    }


def _assertion(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise MachineQaExecutionError("Machine assertions must be objects")
    _require_keys(raw, {"argv", "expected_exit"}, required={"argv"})
    argv = raw.get("argv")
    if not isinstance(argv, list) or not 1 <= len(argv) <= 32 or any(
        not isinstance(value, str) or not value or len(value) > 1000
        for value in argv
    ):
        raise MachineQaExecutionError("assertion argv must be 1..32 strings")
    expected = raw.get("expected_exit", 0)
    if not isinstance(expected, int) or not 0 <= expected <= 255:
        raise MachineQaExecutionError("expected_exit must be 0..255")
    return {"argv": list(argv), "expected_exit": expected}


__all__ = [
    "MACHINE_METHODS",
    "MachineQaExecutionError",
    "validate_machine_method_config",
]
