"""Installer campaign aligned with the current public installer transcript."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

from yoke_core.domain.installer_campaign_key_settle_cases import (
    KEY_SETTLED_INSTALLER_CAMPAIGN_CASES,
)


_RETIRED_STARTUP_TEXT = "Starting Yoke onboard"


def _current_text_case(source: dict[str, Any]) -> dict[str, Any]:
    case = deepcopy(source)
    if case["case_key"] != "cold-start-hosted":
        return case
    for config in case["method_config"]["baseline_configs"].values():
        config["expected_text"] = [
            text
            for text in config["expected_text"]
            if text != _RETIRED_STARTUP_TEXT
        ]
    return case


CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES = tuple(
    _current_text_case(case) for case in KEY_SETTLED_INSTALLER_CAMPAIGN_CASES
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
