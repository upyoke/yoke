"""Closed stdout parsing for the dedicated Test Mac reset receipt."""

from __future__ import annotations

from collections.abc import Mapping

from yoke_harness.ssh_mac_full_reset_contract import (
    EVIDENCE_SOURCE_PATH,
    FULL_RESET_MARKER,
    FULL_RESET_REMOTE_PATH,
    FullResetPathContract,
    HOMEBREW_PATH,
    RESET_FAILURE_PREFIX,
    RESET_LOAD_AVERAGE_PREFIX,
    RESET_PHASES,
    RESET_PROCESS_REAPED_PREFIX,
    RESET_RECOVERY_FAILURE_MARKER,
    RESET_RELATIVE_DIRECTORIES,
    RESET_TEMP_FILES,
    RETAINED_EVIDENCE_DIRECTORY,
    TOKEN_BACKUP_DIRECTORY,
    TOKEN_LOCATIONS,
)


def closed_outcomes(stdout: str) -> dict[str, str | int | float] | None:
    """Parse the six-line success receipt, including process-table facts."""
    lines = tuple(line.strip() for line in stdout.splitlines() if line.strip())
    token_outcomes: dict[str, str] = {}
    evidence_outcome: str | None = None
    reaped: int | None = None
    load_average: str | None = None
    expected_prefixes = {
        f"YOKE_TOKEN_{label}_": label for _source, _backup, label in TOKEN_LOCATIONS
    }
    for line in lines:
        if line == FULL_RESET_MARKER:
            continue
        if line in {
            "YOKE_INSTALLER_EVIDENCE_MOVED",
            "YOKE_INSTALLER_EVIDENCE_RETAINED",
            "YOKE_INSTALLER_EVIDENCE_ABSENT",
        }:
            evidence_outcome = line.removeprefix("YOKE_INSTALLER_EVIDENCE_").lower()
            continue
        if line.startswith(RESET_PROCESS_REAPED_PREFIX):
            try:
                reaped = int(line.removeprefix(RESET_PROCESS_REAPED_PREFIX))
            except ValueError:
                return None
            continue
        if line.startswith(RESET_LOAD_AVERAGE_PREFIX):
            load_average = line.removeprefix(RESET_LOAD_AVERAGE_PREFIX)
            continue
        matched = False
        for prefix, label in expected_prefixes.items():
            if line in {prefix + "RESTORED", prefix + "ABSENT"}:
                token_outcomes[label] = line.removeprefix(prefix).lower()
                matched = True
                break
        if not matched:
            return None
    if (
        len(lines) != 6
        or lines.count(FULL_RESET_MARKER) != 1
        or evidence_outcome is None
        or reaped is None
        or not load_average
        or set(token_outcomes) != set(expected_prefixes.values())
    ):
        return None
    try:
        load_value = float(load_average)
    except ValueError:
        return None
    return {
        **token_outcomes,
        "evidence": evidence_outcome,
        "reaped_processes": reaped,
        "load_average": load_value,
    }


def failure_outcome(stdout: str) -> tuple[str, bool, str | None] | None:
    """Parse a closed failure marker, optionally with process-table detail."""
    lines = tuple(line.strip() for line in stdout.splitlines() if line.strip())
    if len(lines) not in {1, 2} or not lines[0].startswith(RESET_FAILURE_PREFIX):
        return None
    phase = lines[0].removeprefix(RESET_FAILURE_PREFIX)
    phase_names = {value: name for name, value in RESET_PHASES.items()}
    if phase not in phase_names:
        return None
    detail = lines[1] if len(lines) == 2 else None
    recovery_failed = detail is not None and detail == RESET_RECOVERY_FAILURE_MARKER
    if detail is not None and not recovery_failed:
        parts = tuple(detail.split())
        if len(parts) != 3 or any(not part.isdigit() for part in parts[:2]):
            return None
        try:
            float(parts[2])
        except ValueError:
            return None
    return phase_names[phase], recovery_failed, None if recovery_failed else detail


def success_evidence(
    contract: FullResetPathContract,
    outcomes: Mapping[str, str | int | float],
) -> dict[str, object]:
    """Build the success evidence document from a closed receipt."""
    home = contract.home
    rows: list[dict[str, str]] = [
        {"path": f"{home}/.yoke", "outcome": "removed"},
        {
            "path": f"{home}/{EVIDENCE_SOURCE_PATH}",
            "outcome": "moved" if outcomes["evidence"] == "moved" else "absent",
        },
        {
            "path": f"{home}/{RETAINED_EVIDENCE_DIRECTORY}",
            "outcome": (
                "preserved"
                if outcomes["evidence"] in {"moved", "retained"}
                else "absent"
            ),
        },
    ]
    rows.extend(
        {"path": f"{home}/{suffix}", "outcome": "removed"}
        for suffix in RESET_RELATIVE_DIRECTORIES
    )
    rows.extend(
        {"path": path, "outcome": "removed"} for path in contract.tool_file_paths
    )
    rows.extend({"path": path, "outcome": "removed"} for path in RESET_TEMP_FILES)
    rows.append(
        {
            "path": f"{home}/{TOKEN_BACKUP_DIRECTORY}",
            "outcome": "mode-0700",
        }
    )
    for source, backup_name, label in TOKEN_LOCATIONS:
        outcome = outcomes[label]
        rows.extend(
            (
                {
                    "path": f"{home}/{TOKEN_BACKUP_DIRECTORY}/{backup_name}",
                    "outcome": (
                        "preserved-mode-0600" if outcome == "restored" else "not-copied"
                    ),
                },
                {
                    "path": source,
                    "outcome": (
                        "restored-mode-0600" if outcome == "restored" else "absent"
                    ),
                },
            )
        )
    rows.extend(
        (
            {"path": f"{home}/code", "outcome": "children-removed"},
            {"path": HOMEBREW_PATH, "outcome": "uv-absent"},
        )
    )
    rows.extend(
        {
            "path": path,
            "outcome": "cleaned-or-absent",
        }
        for path in contract.startup_files
    )
    rows.extend(
        (
            {
                "path": contract.shell_path,
                "outcome": "login-and-ssh-resolution-clean",
            },
            {
                "path": contract.tool_bin_dir,
                "outcome": "absent-from-login-and-ssh-path",
            },
            {"path": FULL_RESET_REMOTE_PATH, "outcome": "removed"},
        )
    )
    return {
        "paths": rows,
        "path_state": {
            "launcher": contract.launcher_path,
            "launcher_present": False,
            "tool_bin_dir": contract.tool_bin_dir,
            "login_path_present": False,
            "ssh_path_present": False,
        },
        "process_state": {
            "reaped_processes": outcomes["reaped_processes"],
            "surviving_matches": 0,
            "load_average": outcomes["load_average"],
        },
    }


__all__ = ["closed_outcomes", "failure_outcome", "success_evidence"]
