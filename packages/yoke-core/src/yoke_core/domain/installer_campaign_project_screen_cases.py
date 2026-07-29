"""Installer campaign with project-mode input grounded in the visible screen."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

from yoke_core.domain.installer_campaign_plan_common import (
    CHOOSE_MACHINE_ONLY_KEYS,
    PROJECT_MODE_TEXT,
    action,
    transition,
)
from yoke_core.domain.installer_campaign_screen_ready_cases import (
    SCREEN_READY_INSTALLER_CAMPAIGN_CASES,
)


def _project_mode_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    updated = deepcopy(actions)
    insertion = next(
        index
        for index, candidate in enumerate(updated)
        if candidate["step"] == "machine-github-backlog"
    ) + 1
    updated[insertion:insertion] = [
        action("project-mode", ready_text=PROJECT_MODE_TEXT),
        transition(
            "project-mode-machine-only",
            *CHOOSE_MACHINE_ONLY_KEYS,
            ready_text=PROJECT_MODE_TEXT,
            wait_seconds=10,
        ),
    ]
    return updated


def _project_screen_case(source: dict[str, Any]) -> dict[str, Any]:
    case = deepcopy(source)
    if case["case_key"] != "cold-start-hosted":
        return case
    for config in case["method_config"]["baseline_configs"].values():
        config["actions"] = _project_mode_actions(config["actions"])
    return case


PROJECT_SCREEN_INSTALLER_CAMPAIGN_CASES = tuple(
    _project_screen_case(case) for case in SCREEN_READY_INSTALLER_CAMPAIGN_CASES
)


def project_screen_campaign_digest() -> str:
    """Return the stable digest of the project-screen-grounded campaign."""
    encoded = json.dumps(
        PROJECT_SCREEN_INSTALLER_CAMPAIGN_CASES,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "PROJECT_SCREEN_INSTALLER_CAMPAIGN_CASES",
    "project_screen_campaign_digest",
]
