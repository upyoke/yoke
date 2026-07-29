"""Current installer campaign with terminal input grounded in visible screens."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

from yoke_core.domain.installer_campaign_cases import INSTALLER_CAMPAIGN_CASES
from yoke_core.domain.installer_campaign_plan_common import (
    APPLY_SUCCESS_TEXT,
    HOSTED_CONNECTED_TEXT,
    MACHINE_GITHUB_TEXT,
    PARENT_HANDOFF_TEXT,
    REVIEW_TEXT,
)


_READY_TEXT_BY_STEP = {
    "hosted-connected": HOSTED_CONNECTED_TEXT,
    "continue-hosted-connected": HOSTED_CONNECTED_TEXT,
    "machine-github": MACHINE_GITHUB_TEXT,
    "machine-github-backlog": MACHINE_GITHUB_TEXT,
    "review": REVIEW_TEXT,
    "review-frame": REVIEW_TEXT,
    "apply": REVIEW_TEXT,
    "apply-complete": APPLY_SUCCESS_TEXT,
    "exit-apply-success": APPLY_SUCCESS_TEXT,
    "complete-onboarding": PARENT_HANDOFF_TEXT,
}
_EXTENDED_READY_STEPS = {"hosted-connected", "apply-complete"}
_REDUNDANT_HOSTED_PROJECT_STEPS = {
    "project-mode",
    "project-mode-machine-only",
}


def _screen_ready_actions(
    actions: list[dict[str, Any]],
    *,
    hosted_machine_only: bool,
) -> list[dict[str, Any]]:
    ready_actions: list[dict[str, Any]] = []
    for source in actions:
        action = deepcopy(source)
        step = str(action["step"])
        if hosted_machine_only and step in _REDUNDANT_HOSTED_PROJECT_STEPS:
            continue
        ready_text = _READY_TEXT_BY_STEP.get(step)
        if ready_text is not None:
            action["ready_text"] = list(ready_text)
            if step in _EXTENDED_READY_STEPS:
                action["ready_timeout_seconds"] = 180
        ready_actions.append(action)
    return ready_actions


def _screen_ready_case(source: dict[str, Any]) -> dict[str, Any]:
    case = deepcopy(source)
    method_config = case["method_config"]
    if not str(case["method_id"]).startswith("terminal-"):
        return case
    configs = method_config.get("baseline_configs")
    if isinstance(configs, dict):
        for config in configs.values():
            config["actions"] = _screen_ready_actions(
                config["actions"],
                hosted_machine_only=case["case_key"] == "cold-start-hosted",
            )
    else:
        method_config["actions"] = _screen_ready_actions(
            method_config["actions"],
            hosted_machine_only=False,
        )
    return case


SCREEN_READY_INSTALLER_CAMPAIGN_CASES = tuple(
    _screen_ready_case(case) for case in INSTALLER_CAMPAIGN_CASES
)


def screen_ready_campaign_digest() -> str:
    """Return the stable digest of the current screen-grounded campaign."""
    encoded = json.dumps(
        SCREEN_READY_INSTALLER_CAMPAIGN_CASES,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "SCREEN_READY_INSTALLER_CAMPAIGN_CASES",
    "screen_ready_campaign_digest",
]
