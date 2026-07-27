"""Compile the installer scenario catalog into Machine QA plan cases."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from yoke_core.domain.installer_campaign_catalog import (
    INSTALLER_CAMPAIGN_SCENARIOS,
    InstallerCampaignScenario,
)


PUBLIC_INSTALL = "curl -fsSL https://upyoke.com/install | sh"
EXPECTED_CASE_KEYS = tuple(
    scenario.case_key for scenario in INSTALLER_CAMPAIGN_SCENARIOS
)

_AUTOMATIC_TERMINAL_CASES: dict[str, dict[str, Any]] = {
    "install-smoke-001": {
        "entry_surface": PUBLIC_INSTALL,
        "steps": [
            {
                "key": "install-smoke-001",
                "send": "Enter",
                "expect": "Starting Yoke onboard",
                "timeout_seconds": 300,
            }
        ],
    },
    "install-smoke-002": {
        "entry_surface": ("curl -fsSL https://upyoke.com/install | sh -s -- --yes"),
        "steps": [
            {
                "key": "install-smoke-002",
                "expect": "Run yoke onboard",
                "timeout_seconds": 300,
            }
        ],
    },
    "install-uv-003": {
        "entry_surface": PUBLIC_INSTALL,
        "steps": [
            {
                "key": "install-uv-003",
                "send": "Enter",
                "expect": "Starting Yoke onboard",
                "timeout_seconds": 300,
            }
        ],
    },
    "install-uv-007": {
        "entry_surface": (
            "curl -fsSL https://upyoke.com/install | YOKE_INSTALL_YES=1 sh"
        ),
        "steps": [
            {
                "key": "install-uv-007",
                "expect": "Starting Yoke onboard",
                "timeout_seconds": 300,
            }
        ],
    },
    "install-uv-008": {
        "entry_surface": (
            "curl -fsSL https://upyoke.com/install | YOKE_NO_ONBOARD=1 sh"
        ),
        "steps": [
            {
                "key": "install-uv-008",
                "expect": "Run yoke onboard",
                "timeout_seconds": 300,
            }
        ],
    },
}

_MACHINE_ASSERTIONS: dict[str, tuple[tuple[str, ...], ...]] = {
    "state-008": (
        (
            "/bin/zsh",
            "-c",
            "command -v yoke >/dev/null && yoke --version >/dev/null",
        ),
    ),
    "mac-007": (
        (
            "/bin/zsh",
            "-c",
            "command -v uv >/dev/null && command -v uvx >/dev/null "
            "&& command -v yoke >/dev/null",
        ),
    ),
    "mac-010": (
        (
            "/bin/zsh",
            "-lic",
            "command -v yoke >/dev/null",
        ),
        (
            "/bin/zsh",
            "-c",
            "command -v yoke >/dev/null",
        ),
    ),
}

_CASE_BASELINES: dict[str, list[str]] = {
    "path-001": ["fresh-host"],
    "path-002": ["fresh-host"],
    "path-003": ["fresh-host"],
    "path-004": ["shell-preconfigured"],
    "path-005": ["fresh-host"],
    "path-006": ["fresh-host"],
    "state-008": ["shell-preconfigured"],
    "mac-007": ["shell-preconfigured"],
    "mac-010": ["shell-preconfigured"],
    "mac-011": ["fresh-host"],
    "mac-012": ["shell-preconfigured"],
}


def _instructions(scenario: InstallerCampaignScenario) -> str:
    return (
        f"Source scenario: {scenario.source_id}. "
        f"Catalog section: {scenario.wave}. "
        f"Required host profile or precondition: {scenario.host_profile}. "
        f"Exercise this flow: {scenario.flow}."
    )


def _inspection_entry_surface(scenario: InstallerCampaignScenario) -> str:
    key = scenario.case_key
    if key.startswith("install-") or key in {
        "mac-001",
        "mac-011",
        "mac-012",
    }:
        return PUBLIC_INSTALL
    if key == "local-birth-001":
        return "yoke init --local"
    if key in {"self-host-001", "hosted-connect-001"}:
        return "yoke connect"
    return "yoke onboard --post-install"


def _inspection_send(flow: str) -> str:
    lowered = flow.lower()
    if "ctrl-c" in lowered or "quit" in lowered:
        return "C-c"
    if "ctrl-j" in lowered:
        return "C-j"
    if "escape" in lowered or re.search(r"\bback\b", lowered):
        return "Escape"
    if "space selects" in lowered:
        return "Space"
    if "up/down" in lowered:
        return "Down"
    if "leading `~`" in lowered:
        return "~/code/name"
    return "Enter"


def _inspection_expect(scenario: InstallerCampaignScenario) -> str:
    key = scenario.case_key
    if key.startswith("github-"):
        return "GitHub"
    if key.startswith("path-"):
        return "PATH"
    if key.startswith("project-"):
        return "Project"
    if key.startswith("publish-"):
        return "GitHub"
    if key.startswith("apply-"):
        return "Review"
    return "Yoke"


def _terminal_check_case(
    position: int,
    scenario: InstallerCampaignScenario,
) -> dict[str, Any]:
    config = _AUTOMATIC_TERMINAL_CASES[scenario.case_key]
    return {
        "position": position,
        "case_key": scenario.case_key,
        "method_id": "terminal-check",
        "instructions": _instructions(scenario),
        "expected_outcome": scenario.expected_outcome,
        "method_config": {
            "steps": [dict(step) for step in config["steps"]],
            "capture_checkpoints": [],
        },
        "host_baselines": _CASE_BASELINES.get(scenario.case_key, []),
        "entry_surface": str(config["entry_surface"]),
        "required_completion": scenario.case_key,
    }


def _terminal_inspection_case(
    position: int,
    scenario: InstallerCampaignScenario,
) -> dict[str, Any]:
    checkpoint = scenario.case_key
    return {
        "position": position,
        "case_key": checkpoint,
        "method_id": "terminal-inspection",
        "instructions": _instructions(scenario),
        "expected_outcome": scenario.expected_outcome,
        "method_config": {
            "steps": [
                {
                    "key": checkpoint,
                    "send": _inspection_send(scenario.flow),
                    "expect": _inspection_expect(scenario),
                    "timeout_seconds": 300,
                }
            ],
            "capture_checkpoints": [checkpoint],
        },
        "host_baselines": _CASE_BASELINES.get(checkpoint, []),
        "entry_surface": _inspection_entry_surface(scenario),
        "required_completion": checkpoint,
    }


def _machine_state_case(
    position: int,
    scenario: InstallerCampaignScenario,
) -> dict[str, Any]:
    return {
        "position": position,
        "case_key": scenario.case_key,
        "method_id": "machine-state-check",
        "instructions": _instructions(scenario),
        "expected_outcome": scenario.expected_outcome,
        "method_config": {
            "assertions": [
                {"argv": list(argv)} for argv in _MACHINE_ASSERTIONS[scenario.case_key]
            ],
        },
        "host_baselines": _CASE_BASELINES.get(scenario.case_key, []),
        "entry_surface": None,
        "required_completion": None,
    }


def _campaign_case(
    position: int,
    scenario: InstallerCampaignScenario,
) -> dict[str, Any]:
    if scenario.case_key in _AUTOMATIC_TERMINAL_CASES:
        return _terminal_check_case(position, scenario)
    if scenario.case_key in _MACHINE_ASSERTIONS:
        return _machine_state_case(position, scenario)
    return _terminal_inspection_case(position, scenario)


INSTALLER_CAMPAIGN_CASES = tuple(
    _campaign_case(position, scenario)
    for position, scenario in enumerate(
        INSTALLER_CAMPAIGN_SCENARIOS,
        start=1,
    )
)


def campaign_contract_digest() -> str:
    """Fingerprint the complete case contract bound by the migration source."""
    encoded = json.dumps(
        INSTALLER_CAMPAIGN_CASES,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "EXPECTED_CASE_KEYS",
    "INSTALLER_CAMPAIGN_CASES",
    "campaign_contract_digest",
]
