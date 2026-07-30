"""Bounded declarative contracts for installer-campaign Machine QA cases."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.machine_qa_action_readiness_contract import (
    normalize_action_readiness,
    registered_terminal_post_check,
)
from yoke_core.domain.machine_qa_operator_gate_contract import (
    normalize_operator_gate,
)


REGISTERED_SETUP_OPERATION_IDS = frozenset(
    {
        "fixture.apply-resume-report-prepare",
        "fixture.git-checkout-prepare",
        "fixture.git-remote-prepare",
        "fixture.project-registrations-prepare",
        "fixture.source-dev-checkout-prepare",
        "fixture.source-dev-remote-prepare",
        "fixture.yoke-api-start",
        "installer-campaign.workspace-reset",
        "installer.current-release-prepare",
        "installer.product-state-reset",
        "machine.path-idempotence-prepare",
        "machine.path-prepare",
        "machine.token-file-prepare",
        "machine.yoke-auth-clear",
        "machine.yoke-connection-prepare",
        "machine.yoke-connection-restore",
        "machine.yoke-connections-prepare",
        "terminal.size-prepare",
    }
)
REGISTERED_POST_STATE_ASSERTION_IDS = frozenset(
    {
        "source-dev.checkout-state-assert",
    }
)
REGISTERED_STAGE_URLS = frozenset(
    {
        "https://api.upyoke.com/install",
    }
)
_MAX_ACTIONS = 100
_MAX_OPERATIONS = 50
_MAX_TEXT_VALUES = 100


class MachineQaRecipeError(ValueError):
    """A declarative Machine QA recipe is outside the registered contract."""


def execution_blocker(config: Mapping[str, Any]) -> dict[str, Any] | None:
    """Validate and return an explicit non-executable precondition."""
    raw = config.get("execution_blocker")
    if raw is None:
        return None
    if set(config) != {"execution_blocker"} or not isinstance(raw, Mapping):
        raise MachineQaRecipeError(
            "execution_blocker must be the case's only method_config field"
        )
    if set(raw) != {"code", "reason"}:
        raise MachineQaRecipeError("execution_blocker requires exactly code and reason")
    code = str(raw.get("code") or "").strip()
    reason = str(raw.get("reason") or "").strip()
    if not code or len(code) > 160 or not reason or len(reason) > 2000:
        raise MachineQaRecipeError("execution_blocker text is empty or too long")
    return {"code": code, "reason": reason}


def _strings(
    raw: Any,
    *,
    field: str,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(raw, list) or len(raw) > _MAX_TEXT_VALUES:
        raise MachineQaRecipeError(f"{field} must be a bounded list")
    values = [str(value) for value in raw]
    if (not allow_empty and not values) or any(
        not value or len(value) > 4000 for value in values
    ):
        raise MachineQaRecipeError(f"{field} contains empty or oversized text")
    return values


def _operation_refs(
    raw: Any,
    *,
    field: str,
    allowed_ids: frozenset[str],
) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) > _MAX_OPERATIONS:
        raise MachineQaRecipeError(f"{field} must be a bounded list")
    normalized: list[dict[str, Any]] = []
    for operation in raw:
        if (
            not isinstance(operation, Mapping)
            or set(operation) != {"id", "parameters"}
            or not isinstance(operation.get("parameters"), Mapping)
        ):
            raise MachineQaRecipeError(
                f"{field} entries require exactly id and parameters"
            )
        operation_id = str(operation.get("id") or "")
        if operation_id not in allowed_ids:
            raise MachineQaRecipeError(
                f"{field} names unregistered operation {operation_id!r}"
            )
        normalized.append(
            {
                "id": operation_id,
                "parameters": dict(operation["parameters"]),
            }
        )
    return normalized


def validate_fixture_operation_refs(
    config: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Normalize the shared closed fixture-operation vocabulary."""
    return {
        "post_state_assertions": _operation_refs(
            config.get("post_state_assertions", []),
            field="post_state_assertions",
            allowed_ids=REGISTERED_POST_STATE_ASSERTION_IDS,
        ),
        "setup_operations": _operation_refs(
            config.get("setup_operations", []),
            field="setup_operations",
            allowed_ids=REGISTERED_SETUP_OPERATION_IDS,
        ),
    }


def _actions(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= _MAX_ACTIONS:
        raise MachineQaRecipeError("actions must contain 1..100 entries")
    normalized: list[dict[str, Any]] = []
    for action in raw:
        if not isinstance(action, Mapping):
            raise MachineQaRecipeError("actions must be objects")
        allowed = {
            "step",
            "keys",
            "capture",
            "completion_text",
            "gate_timeout_seconds",
            "operator_gate",
            "ready_text",
            "ready_timeout_seconds",
            "wait_seconds",
        }
        unknown = set(action) - allowed
        if unknown:
            raise MachineQaRecipeError(
                f"action has unknown fields: {sorted(unknown)!r}"
            )
        step = str(action.get("step") or "").strip()
        if not step or len(step) > 160:
            raise MachineQaRecipeError("action step is empty or too long")
        keys = _strings(
            action.get("keys", []),
            field="action keys",
            allow_empty=True,
        )
        capture = action.get("capture", True)
        if not isinstance(capture, bool):
            raise MachineQaRecipeError("action capture must be boolean")
        normalized_action: dict[str, Any] = {
            "step": step,
            "keys": keys,
            "capture": capture,
        }
        try:
            normalized_action.update(
                normalize_action_readiness(action, strings=_strings)
            )
        except ValueError as exc:
            raise MachineQaRecipeError(str(exc)) from exc
        if "wait_seconds" in action:
            wait_seconds = action["wait_seconds"]
            if (
                isinstance(wait_seconds, bool)
                or not isinstance(wait_seconds, (int, float))
                or not 0 <= float(wait_seconds) <= 300
            ):
                raise MachineQaRecipeError(
                    "action wait_seconds must be numeric from 0..300"
                )
            normalized_action["wait_seconds"] = float(wait_seconds)
        try:
            normalize_operator_gate(
                action,
                normalized_action,
                strings=_strings,
            )
        except ValueError as exc:
            raise MachineQaRecipeError(str(exc)) from exc
        normalized.append(normalized_action)
    return normalized


def validate_terminal_recipe(
    config: Mapping[str, Any],
    *,
    required_completion: str | None,
) -> dict[str, Any]:
    """Validate the lossless typed contract ported from the live campaign."""
    required = {
        "actions",
        "capture_checkpoints",
        "execution_mode",
        "expected_return_codes",
        "expected_text",
        "max_wall_seconds",
        "notes",
        "post_checks",
        "setup_operations",
        "start_delay",
        "step_delay",
    }
    allowed = required | {"post_state_assertions", "stage_files"}
    missing = sorted(required - set(config))
    unknown = sorted(set(config) - allowed)
    if missing or unknown:
        raise MachineQaRecipeError(
            f"invalid recipe fields; missing={missing}, unknown={unknown}"
        )
    actions = _actions(config["actions"])
    completion = str(required_completion or "").strip()
    if not completion or completion not in {action["step"] for action in actions}:
        raise MachineQaRecipeError("required_completion must name a typed action step")
    mode = str(config["execution_mode"])
    if mode not in {"terminal", "ssh-command"}:
        raise MachineQaRecipeError("execution_mode is not registered")
    if mode == "ssh-command" and (len(actions) != 1 or actions[0]["keys"]):
        raise MachineQaRecipeError(
            "ssh-command recipes require one action without keys"
        )
    expected_codes = config["expected_return_codes"]
    if (
        not isinstance(expected_codes, list)
        or not 1 <= len(expected_codes) <= 16
        or any(
            not isinstance(value, int) or not 0 <= value <= 255
            for value in expected_codes
        )
    ):
        raise MachineQaRecipeError(
            "expected_return_codes must contain 1..16 exit codes"
        )
    start_delay = config["start_delay"]
    step_delay = config["step_delay"]
    max_wall = config["max_wall_seconds"]
    if (
        not isinstance(start_delay, (int, float))
        or not 0 <= float(start_delay) <= 300
        or not isinstance(step_delay, (int, float))
        or not 0 <= float(step_delay) <= 60
        or not isinstance(max_wall, (int, float))
        or not 1 <= float(max_wall) <= 7200
    ):
        raise MachineQaRecipeError("recipe timing is outside registered bounds")
    notes = str(config["notes"])
    if not notes or len(notes) > 4000:
        raise MachineQaRecipeError("recipe notes are empty or too long")
    checkpoints = _strings(
        config["capture_checkpoints"],
        field="capture_checkpoints",
        allow_empty=True,
    )
    action_steps = {action["step"] for action in actions}
    if any(checkpoint not in action_steps for checkpoint in checkpoints):
        raise MachineQaRecipeError("capture_checkpoints name unknown action steps")
    post_checks = _strings(config["post_checks"], field="post_checks")
    if any(not registered_terminal_post_check(value) for value in post_checks):
        raise MachineQaRecipeError("post_checks name an unregistered check")
    stage_files: list[dict[str, str]] = []
    raw_stage_files = config.get("stage_files", [])
    if not isinstance(raw_stage_files, list) or len(raw_stage_files) > 20:
        raise MachineQaRecipeError("stage_files must be a bounded list")
    for staged in raw_stage_files:
        if not isinstance(staged, Mapping):
            raise MachineQaRecipeError("stage_files must be objects")
        source_keys = {"source_path", "source_url"} & set(staged)
        if len(source_keys) != 1 or set(staged) != source_keys | {"remote_path"}:
            raise MachineQaRecipeError(
                "stage_files require remote_path and exactly one source"
            )
        source_key = next(iter(source_keys))
        source = str(staged[source_key])
        remote = str(staged["remote_path"])
        if not remote.startswith("/") or len(source) > 1000 or len(remote) > 1000:
            raise MachineQaRecipeError(
                "stage file paths must be bounded and remote must be absolute"
            )
        if source_key == "source_path" and not (
            source.startswith("/") or source.startswith("~/")
        ):
            raise MachineQaRecipeError(
                "stage source_path must be absolute or home-relative"
            )
        if source_key == "source_url" and source not in REGISTERED_STAGE_URLS:
            raise MachineQaRecipeError("stage source_url is not registered")
        stage_files.append(
            {
                source_key: source,
                "remote_path": remote,
            }
        )
    fixture_operations = validate_fixture_operation_refs(config)
    return {
        "actions": actions,
        "capture_checkpoints": checkpoints,
        "execution_mode": mode,
        "expected_return_codes": list(expected_codes),
        "expected_text": _strings(
            config["expected_text"],
            field="expected_text",
        ),
        "max_wall_seconds": float(max_wall),
        "notes": notes,
        "post_checks": post_checks,
        "post_state_assertions": fixture_operations["post_state_assertions"],
        "setup_operations": fixture_operations["setup_operations"],
        "stage_files": stage_files,
        "start_delay": float(start_delay),
        "step_delay": float(step_delay),
    }


__all__ = [
    "MachineQaRecipeError",
    "REGISTERED_POST_STATE_ASSERTION_IDS",
    "REGISTERED_STAGE_URLS",
    "REGISTERED_SETUP_OPERATION_IDS",
    "execution_blocker",
    "validate_fixture_operation_refs",
    "validate_terminal_recipe",
]
