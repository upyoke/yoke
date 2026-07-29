"""Installer campaign with settled multi-key input and complete screen gates."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

from yoke_core.domain.installer_campaign_plan_common import PROJECT_MODE_TEXT
from yoke_core.domain.installer_campaign_project_screen_cases import (
    PROJECT_SCREEN_INSTALLER_CAMPAIGN_CASES,
)


def _settled_case(source: dict[str, Any]) -> dict[str, Any]:
    case = deepcopy(source)
    if case["case_key"] != "apply-handoff":
        return case
    for action in case["method_config"]["actions"]:
        if action["step"] == "project-mode":
            action["ready_text"] = list(PROJECT_MODE_TEXT)
    return case


KEY_SETTLED_INSTALLER_CAMPAIGN_CASES = tuple(
    _settled_case(case) for case in PROJECT_SCREEN_INSTALLER_CAMPAIGN_CASES
)


def key_settled_campaign_digest() -> str:
    """Return the stable digest of the fully screen-gated campaign."""
    encoded = json.dumps(
        KEY_SETTLED_INSTALLER_CAMPAIGN_CASES,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "KEY_SETTLED_INSTALLER_CAMPAIGN_CASES",
    "key_settled_campaign_digest",
]
