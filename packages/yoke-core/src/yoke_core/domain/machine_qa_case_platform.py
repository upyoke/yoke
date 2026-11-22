"""Platform constraints derived from a QA case's executable declarations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from yoke_contracts.machine_config.test_machine import (
    TEST_MACHINE_OSES,
    TestMachineCapabilityError,
    normalize_test_machine_capability_tags,
    test_machine_capability_tags,
)

# Only execution inputs participate; expected screen text and outcomes can
# mention other operating systems without requiring those hosts. Windows words
# mean native Windows; a WSL case declares os ``wsl``.
_PLATFORM_WORDS = {
    "linux": r"\b(?:linux|ubuntu|debian|xfce|xfce4-terminal)\b",
    "macos": r"\b(?:macos|darwin|osascript|safari|terminal\.app)\b|\bmac os\b",
    "windows": r"\b(?:powershell|pwsh|cmd\.exe)\b|(?-i:\bWindows\b)",
}
_STEP_KEYS = frozenset(
    {
        "argv",
        "command",
        "commands",
        "steps",
        "assertions",
        "setup_operations",
        "baseline_configs",
        "os",
    }
)


def _execution_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join(
            _execution_text(v)
            for key, v in value.items()
            if key
            not in {
                "expected_text",
                "ready_text",
                "completion_text",
                "notes",
                "instructions",
                "expected_outcome",
            }
        )
    if isinstance(value, (list, tuple)):
        return " ".join(_execution_text(v) for v in value)
    return str(value or "")


def platform_config(config: Mapping[str, Any]) -> dict[str, str]:
    """Validate the ``os`` metadata shared by machine method contracts."""
    result = {"os": config["os"]} if "os" in config else {}
    if any(
        not isinstance(value, str) or value not in TEST_MACHINE_OSES
        for value in result.values()
    ):
        raise TestMachineCapabilityError(
            "test_machine_platform_invalid: set method_config.os to linux, "
            "macos, windows (native) or wsl"
        )
    return result


def case_platform(
    case: Mapping[str, Any], *, allow_undeclared: bool = False,
) -> str | None:
    """Resolve declared execution inputs to the OS of the case's driving host."""
    from yoke_contracts.qa_case_starting_state import declares_starting_state

    from yoke_core.domain.machine_qa_case_hosts import driver_slot_os

    if case.get("runner_id") == "agent_mission" and not declares_starting_state(case):
        return None
    if slot_os := driver_slot_os(case):
        return slot_os
    config = case.get("method_config") or {}
    declared_os = set(platform_config(config).values())
    from yoke_core.domain.qa_method_capabilities import capability_kinds

    required = tuple(
        kind
        for field in ("required_capability_kinds", "capability_requirements")
        for kind in capability_kinds(case.get(field), subject="QA case")
    )
    text = " ".join(
        [
            _execution_text(required),
            _execution_text(
                {key: value for key, value in config.items() if key in _STEP_KEYS}
            ),
        ]
    )
    platforms = declared_os | {
        os for os, pattern in _PLATFORM_WORDS.items() if re.search(pattern, text, re.I)
    }
    if re.search(r"\bwindows\b", _execution_text(required), re.I):
        platforms.add("windows")
    # GNU stat's mode option is used by Linux machine-state assertions.
    if re.search(r"\bstat\s+-c\b", text):
        platforms.add("linux")
    if len(platforms) > 1:
        raise TestMachineCapabilityError(
            "test_machine_platform_ambiguous: case "
            f"{case.get('case_key') or case.get('requirement_id') or 'unknown'} "
            f"declares {', '.join(sorted(platforms))}; split platform-specific "
            "steps into separate cases before running QA"
        )
    if platforms:
        return next(iter(platforms))
    if allow_undeclared:
        return None
    raise TestMachineCapabilityError(
        "test_machine_platform_undeclared: case "
        f"{case.get('case_key') or case.get('requirement_id') or 'unknown'} "
        "has no declared platform; set method_config.os to linux, macos, windows "
        "(native) or wsl, or list OS slots in method_config.test_machines"
    )


def required_platform(
    cases: Sequence[Mapping[str, Any]], *, allow_undeclared: bool = False,
) -> str | None:
    platforms = {
        platform for case in cases
        if (platform := case_platform(case, allow_undeclared=allow_undeclared))
    }
    if len(platforms) > 1:
        raise TestMachineCapabilityError(
            "test_machine_platform_conflict: one host cannot execute cases requiring "
            f"{', '.join(sorted(platforms))}; run separate platform rosters"
        )
    return next(iter(platforms), None)


def required_host_tags(cases: Sequence[Mapping[str, Any]]) -> set[str]:
    return {
        tag
        for case in cases
        for tag in normalize_test_machine_capability_tags(
            (case.get("method_config") or {}).get("capability_tags", [])
        )
    }


def require_host_tags(settings: Mapping[str, str], cases: Sequence[Mapping[str, Any]]) -> None:
    missing = required_host_tags(cases).difference(test_machine_capability_tags(settings))
    if missing:
        raise TestMachineCapabilityError(
            f"test_machine_capability_tags_unavailable: {settings['resource_name']} "
            f"lacks required tags {', '.join(sorted(missing))}; select a Test Machine "
            "with the required capability_tags or correct the case's declared tags"
        )


def matching_platform_hosts(
    candidates: list[Any], cases: Sequence[Mapping[str, Any]]
) -> list[Any]:
    """Filter before taking any lease, including explicit machine selections."""
    platform = required_platform(cases)
    matching = [
        host
        for host in candidates
        if platform is None or host.settings["os"] == platform
    ]
    if not matching and platform is not None:
        available = (
            ", ".join(
                f"{host.settings['resource_name']} ({host.settings['os']})"
                for host in candidates
            )
            or "none"
        )
        raise TestMachineCapabilityError(
            f"test_machine_platform_unavailable: QA requires {platform}; "
            f"selected registered hosts: {available}. Register and verify a "
            f"{platform} Test Machine for this project, then rerun with its "
            "--test-machine TEST_MACHINE; correct any incompatible case or run pin first"
        )
    return matching
