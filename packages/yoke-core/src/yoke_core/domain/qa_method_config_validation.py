"""Method-specific validation for executable QA plan-case configuration."""

from __future__ import annotations

from typing import Any

from yoke_contracts.browser_qa_contract import (
    browser_method_contract_violation,
)


class QaMethodConfigError(ValueError):
    """A case configuration does not satisfy its method contract."""


def validate_method_config(config_contract_id: str, raw: Any) -> dict:
    """Normalize config through the contract selected by the method row."""
    if raw is None:
        config: dict = {}
    elif isinstance(raw, dict):
        config = dict(raw)
    else:
        raise QaMethodConfigError("method_config must be a JSON object")
    if config_contract_id in {"command", "command-ci"}:
        command = config.get("command")
        if not isinstance(command, str) or not command.strip():
            raise QaMethodConfigError(
                "Command cases require a non-empty method_config.command"
            )
        config["command"] = command.strip()
        timeout = config.get("timeout_seconds")
        if timeout is not None and (
            not isinstance(timeout, int) or timeout < 1 or timeout > 7200
        ):
            raise QaMethodConfigError(
                "Command timeout_seconds must be between 1 and 7200"
            )
        requires_base_url = config.get("requires_base_url")
        if requires_base_url is not None and not isinstance(
            requires_base_url,
            bool,
        ):
            raise QaMethodConfigError("Command requires_base_url must be true or false")
        if config_contract_id == "command-ci":
            workflow = config.get("ci_workflow")
            if not isinstance(workflow, str) or not workflow.strip():
                raise QaMethodConfigError(
                    "CI command cases require a non-empty "
                    "method_config.ci_workflow"
                )
            config["ci_workflow"] = workflow.strip()
    elif config_contract_id in {"browser-check", "browser-inspection"}:
        steps = config.get("steps")
        if not isinstance(steps, list) or not steps:
            raise QaMethodConfigError(
                f"{config_contract_id} cases require a non-empty method_config.steps"
            )
        if any(
            not isinstance(step, dict)
            or not isinstance(step.get("action"), str)
            or not step["action"]
            for step in steps
        ):
            raise QaMethodConfigError(
                f"{config_contract_id} steps require a non-empty action"
            )
        base_url = config.get("base_url")
        if base_url is not None and (
            not isinstance(base_url, str) or not base_url.strip()
        ):
            raise QaMethodConfigError(
                f"{config_contract_id} base_url must be a non-empty string"
            )
        violation = browser_method_contract_violation(config_contract_id, steps)
        if violation is not None:
            raise QaMethodConfigError(violation.message)
    return config


__all__ = [
    "QaMethodConfigError",
    "validate_method_config",
]
