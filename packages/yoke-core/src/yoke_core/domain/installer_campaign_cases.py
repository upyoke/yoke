"""Exact code-owned installer campaign cases for the Machine QA plan."""

from __future__ import annotations

import hashlib
import json

from yoke_core.domain.installer_campaign_plan_machine_state import (
    PATH_ON_SHELL,
    TOKEN_PERMS,
    UNIVERSE_BORN,
)
from yoke_core.domain.installer_campaign_plan_terminal_checks import (
    APPLY_HANDOFF,
    COLD_START_HOSTED,
    HOSTED_CONNECT,
    PATH_REPAIR,
)
from yoke_core.domain.installer_campaign_plan_terminal_inspections import (
    CONNECT_WAIT,
    REVIEW_FRAME,
    WELCOME_FRAME,
)


INSTALLER_CAMPAIGN_CASES = (
    PATH_ON_SHELL,
    WELCOME_FRAME,
    COLD_START_HOSTED,
    HOSTED_CONNECT,
    PATH_REPAIR,
    APPLY_HANDOFF,
    CONNECT_WAIT,
    REVIEW_FRAME,
    TOKEN_PERMS,
    UNIVERSE_BORN,
)
EXPECTED_CASE_KEYS = tuple(case["case_key"] for case in INSTALLER_CAMPAIGN_CASES)
EXPECTED_METHOD_COUNTS = {
    "terminal-check": 4,
    "terminal-inspection": 3,
    "machine-state-check": 3,
}
EXPECTED_REQUIREMENT_COUNT = 12


def _require_exact_contract() -> None:
    if len(INSTALLER_CAMPAIGN_CASES) != 10:
        raise RuntimeError("installer campaign must contain exactly ten cases")
    if tuple(case["position"] for case in INSTALLER_CAMPAIGN_CASES) != tuple(
        range(1, 11)
    ):
        raise RuntimeError("installer campaign positions must be contiguous")
    actual_methods = {
        method: sum(case["method_id"] == method for case in INSTALLER_CAMPAIGN_CASES)
        for method in EXPECTED_METHOD_COUNTS
    }
    if actual_methods != EXPECTED_METHOD_COUNTS:
        raise RuntimeError(
            f"installer campaign method split differs: {actual_methods!r}"
        )
    baseline_cases = {
        case["case_key"]: case["host_baselines"]
        for case in INSTALLER_CAMPAIGN_CASES
        if case["host_baselines"]
    }
    if baseline_cases != {
        "cold-start-hosted": ["fresh-host", "shell-preconfigured"],
        "path-on-shell": ["fresh-host", "shell-preconfigured"],
    }:
        raise RuntimeError(
            f"installer campaign baseline roster differs: {baseline_cases!r}"
        )
    expanded = sum(
        max(1, len(case["host_baselines"])) for case in INSTALLER_CAMPAIGN_CASES
    )
    if expanded != EXPECTED_REQUIREMENT_COUNT:
        raise RuntimeError(
            f"installer campaign expands to {expanded}, expected 12 requirements"
        )


_require_exact_contract()


def campaign_contract_digest() -> str:
    """Stable digest binding the migration to the exact ten-case contract."""
    encoded = json.dumps(
        INSTALLER_CAMPAIGN_CASES,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "EXPECTED_CASE_KEYS",
    "EXPECTED_METHOD_COUNTS",
    "EXPECTED_REQUIREMENT_COUNT",
    "INSTALLER_CAMPAIGN_CASES",
    "campaign_contract_digest",
]
