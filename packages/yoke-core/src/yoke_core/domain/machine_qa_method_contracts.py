"""Bounded case-input contracts for the three Machine QA methods."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.host_baseline_operations import (
    HOST_BASELINE_OPERATIONS,
)
from yoke_core.domain.machine_qa_recipe_contracts import (
    MachineQaRecipeError,
    execution_blocker,
    validate_fixture_operation_refs,
    validate_terminal_recipe,
)


MACHINE_METHODS = frozenset(
    {
        "terminal-check",
        "terminal-inspection",
        "machine-state-check",
    }
)
_REGISTERED_HOST_BASELINES = frozenset(HOST_BASELINE_OPERATIONS)
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
    host_baseline: str | None = None,
) -> dict[str, Any]:
    """Validate bounded structured case input; shell strings are never accepted."""
    if method_id not in MACHINE_METHODS:
        raise MachineQaExecutionError(f"unknown Machine QA method {method_id!r}")
    if not isinstance(config, Mapping):
        raise MachineQaExecutionError("method_config must be an object")
    if host_baseline is not None and host_baseline not in _REGISTERED_HOST_BASELINES:
        raise MachineQaExecutionError(
            f"unknown registered host baseline {host_baseline!r}"
        )
    if "baseline_configs" in config:
        if set(config) != {"baseline_configs"}:
            raise MachineQaExecutionError(
                "baseline_configs must be the only method_config field"
            )
        raw_variants = config["baseline_configs"]
        if not isinstance(raw_variants, Mapping):
            raise MachineQaExecutionError("baseline_configs must be an object")
        actual_names = set(raw_variants)
        if actual_names != _REGISTERED_HOST_BASELINES:
            missing = sorted(_REGISTERED_HOST_BASELINES - actual_names)
            unknown = sorted(
                actual_names - _REGISTERED_HOST_BASELINES,
                key=str,
            )
            raise MachineQaExecutionError(
                "baseline_configs must name exactly the registered host baselines; "
                f"missing={missing}, unknown={unknown}"
            )
        if host_baseline is not None:
            return _validate_baseline_variant(
                method_id,
                raw_variants[host_baseline],
                entry_surface=entry_surface,
                required_completion=required_completion,
            )
        return {
            "baseline_configs": {
                name: _validate_baseline_variant(
                    method_id,
                    raw_variants[name],
                    entry_surface=entry_surface,
                    required_completion=required_completion,
                )
                for name in sorted(_REGISTERED_HOST_BASELINES)
            }
        }
    return _validate_single_method_config(
        method_id,
        config,
        entry_surface=entry_surface,
        required_completion=required_completion,
    )


def _validate_baseline_variant(
    method_id: str,
    raw: Any,
    *,
    entry_surface: str | None,
    required_completion: str | None,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise MachineQaExecutionError(
            "baseline_configs values must be method_config objects"
        )
    if "baseline_configs" in raw:
        raise MachineQaExecutionError("baseline_configs cannot be nested")
    return _validate_single_method_config(
        method_id,
        raw,
        entry_surface=entry_surface,
        required_completion=required_completion,
    )


def _validate_single_method_config(
    method_id: str,
    config: Mapping[str, Any],
    *,
    entry_surface: str | None,
    required_completion: str | None,
) -> dict[str, Any]:
    try:
        blocker = execution_blocker(config)
    except MachineQaRecipeError as exc:
        raise MachineQaExecutionError(str(exc)) from exc
    if blocker is not None:
        return {"execution_blocker": blocker}
    if method_id in {"terminal-check", "terminal-inspection"}:
        if "actions" in config:
            try:
                return validate_terminal_recipe(
                    config,
                    required_completion=required_completion,
                )
            except MachineQaRecipeError as exc:
                raise MachineQaExecutionError(str(exc)) from exc
        _require_keys(
            config,
            {"steps", "capture_checkpoints"},
            required={"steps"},
        )
        if not str(entry_surface or "").strip() or len(str(entry_surface)) > 2000:
            raise MachineQaExecutionError("Terminal cases require entry_surface")
        if not str(required_completion or "").strip():
            raise MachineQaExecutionError("Terminal cases require required_completion")
        steps = config.get("steps")
        if not isinstance(steps, list) or not 1 <= len(steps) <= _MAX_STEPS:
            raise MachineQaExecutionError("Terminal cases require 1..100 steps")
        normalized_steps = [
            _terminal_step(row, index) for index, row in enumerate(steps, start=1)
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
            not isinstance(value, str) or not value.strip() for value in checkpoints
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
    _require_keys(
        config,
        {"assertions", "post_state_assertions", "setup_operations"},
        required={"assertions"},
    )
    assertions = config.get("assertions")
    if not isinstance(assertions, list) or not 1 <= len(assertions) <= _MAX_ASSERTIONS:
        raise MachineQaExecutionError("Machine state cases require 1..50 assertions")
    try:
        fixture_operations = validate_fixture_operation_refs(config)
    except MachineQaRecipeError as exc:
        raise MachineQaExecutionError(str(exc)) from exc
    return {
        "assertions": [_assertion(row) for row in assertions],
        **fixture_operations,
    }


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
    if not key or len(key) > 80 or not expect or len(expect) > 2000 or len(send) > 2000:
        raise MachineQaExecutionError("Terminal step text is empty or too long")
    if not isinstance(timeout, int) or not 1 <= timeout <= 300:
        raise MachineQaExecutionError("Terminal timeout_seconds must be 1..300")
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
    if (
        not isinstance(argv, list)
        or not 1 <= len(argv) <= 32
        or any(
            not isinstance(value, str) or not value or len(value) > 1000
            for value in argv
        )
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
