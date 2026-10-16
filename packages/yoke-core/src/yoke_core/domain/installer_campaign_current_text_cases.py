"""Installer campaign aligned with the current public installer transcript."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

from yoke_core.domain.installer_campaign_key_settle_cases import (
    KEY_SETTLED_INSTALLER_CAMPAIGN_CASES,
)
from yoke_core.domain.installer_campaign_plan_common import action, transition


_RETIRED_STARTUP_TEXT = "Starting Yoke setup"


def _current_text_case(source: dict[str, Any]) -> dict[str, Any]:
    case = deepcopy(source)
    if case["case_key"] == "token-perms":
        checks = (
            (
                "token-file-exists",
                'files=("$HOME"/.yoke/secrets/*.token(N)); (( ${#files[@]} > 0 ))',
            ),
            (
                "secrets-directory-mode-700",
                "[[ $(/usr/bin/stat -f '%Lp' \"$HOME/.yoke/secrets\") == 700 ]]",
            ),
            (
                "token-file-modes-600",
                'files=("$HOME"/.yoke/secrets/*.token(N)); (( ${#files[@]} > 0 )); for file in "${files[@]}"; do [[ $(/usr/bin/stat -f \'%Lp\' "$file") == 600 ]] || exit 1; done',
            ),
        )
        case["method_config"]["assertions"] = [
            {"argv": ["/bin/zsh", "-c", f"set -eu; printf '%s\\n' {name}; {command}"]}
            for name, command in checks
        ]
    if case["case_key"] == "review-frame":
        config = case["method_config"]
        config["actions"].extend(
            [
                transition(
                    "show-all-changes", "Down", "Enter", ready_text=["Show all changes"]
                ),
                action(
                    "pending-write-list",
                    ready_text=["Show summary", "Save your API token (owner-only)"],
                ),
                transition("back-before-apply", "Escape", ready_text=["Show summary"]),
            ]
        )
        config["expected_text"].extend(
            ["Show summary", "Save your API token (owner-only)"]
        )
        config["capture_checkpoints"].append("pending-write-list")
        case["required_completion"] = "back-before-apply"
        case["instructions"] += (
            " Select Show all changes, capture the named pending writes, then back out without Apply."
        )
    if case["case_key"] != "cold-start-hosted":
        return case
    for config in case["method_config"]["baseline_configs"].values():
        config["expected_text"] = [
            text for text in config["expected_text"] if text != _RETIRED_STARTUP_TEXT
        ]
    return case


_ORDER = (
    "path-on-shell",
    "welcome-frame",
    "cold-start-hosted",
    "token-perms",
    "hosted-connect",
    "path-repair",
    "apply-handoff",
    "universe-born",
    "connect-wait",
    "review-frame",
)
_BY_KEY = {case["case_key"]: case for case in KEY_SETTLED_INSTALLER_CAMPAIGN_CASES}
CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES = tuple(
    {**_current_text_case(_BY_KEY[key]), "position": position}
    for position, key in enumerate(_ORDER, 1)
)


def current_text_campaign_digest() -> str:
    """Return the stable digest of the current-transcript campaign."""
    encoded = json.dumps(
        CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES",
    "current_text_campaign_digest",
]
