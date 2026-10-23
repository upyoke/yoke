"""Platform constraints derived from a QA case's executable declarations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from yoke_contracts.machine_config.test_machine import TestMachineCapabilityError

# Only execution inputs participate; expected screen text and outcomes can
# mention other operating systems without requiring those hosts.
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
        "platform",
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
    """Validate the platform metadata shared by machine method contracts."""
    result = {key: config[key] for key in ("os", "platform") if key in config}
    if any(
        not isinstance(value, str) or value not in _PLATFORM_WORDS
        for value in result.values()
    ):
        raise TestMachineCapabilityError(
            "test_machine_platform_invalid: set method_config.os or "
            "method_config.platform to linux, macos or windows"
        )
    if len(set(result.values())) > 1:
        raise TestMachineCapabilityError(
            "test_machine_platform_ambiguous: method_config.os and "
            "method_config.platform disagree; set both to the same OS"
        )
    return result


def case_platform(
    case: Mapping[str, Any], hosts: Mapping[str, str] | None = None
) -> str | None:
    """Resolve declared execution inputs and registered machines to an OS."""
    config = case.get("method_config") or {}
    text = " ".join(
        [
            _execution_text(
                case.get("required_capability_kinds")
                or case.get("capability_requirements")
            ),
            _execution_text(
                {key: value for key, value in config.items() if key in _STEP_KEYS}
            ),
        ]
    )
    platforms = {
        os for os, pattern in _PLATFORM_WORDS.items() if re.search(pattern, text, re.I)
    }
    identifiers = _execution_text(
        [
            case.get("required_capability_kinds"),
            case.get("capability_requirements"),
            config.get("os"),
            config.get("platform"),
        ]
    )
    if re.search(r"\bwindows\b", identifiers, re.I):
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
    from yoke_core.domain.machine_qa_case_hosts import case_machines

    declared = {hosts[name] for name in case_machines(case) if hosts and name in hosts}
    if declared:
        return next(iter(declared)) if len(declared) == 1 else None
    raise TestMachineCapabilityError(
        "test_machine_platform_undeclared: case "
        f"{case.get('case_key') or case.get('requirement_id') or 'unknown'} "
        "has no declared platform; set method_config.os to linux, macos or windows, "
        "or set method_config.machine to a registered Test Machine with an os"
    )


def required_platform(
    cases: Sequence[Mapping[str, Any]], hosts: Mapping[str, str] | None = None
) -> str | None:
    platforms = {platform for case in cases if (platform := case_platform(case, hosts))}
    if len(platforms) > 1:
        raise TestMachineCapabilityError(
            "test_machine_platform_conflict: one host cannot execute cases requiring "
            f"{', '.join(sorted(platforms))}; run separate platform rosters"
        )
    return next(iter(platforms), None)


def matching_platform_hosts(
    candidates: list[Any], cases: Sequence[Mapping[str, Any]]
) -> list[Any]:
    """Filter before taking any lease, including explicit machine selections."""
    platform = required_platform(
        cases,
        {host.settings["resource_name"]: host.settings["os"] for host in candidates},
    )
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
            "--machine NAME; correct any incompatible case or run pin first"
        )
    return matching
