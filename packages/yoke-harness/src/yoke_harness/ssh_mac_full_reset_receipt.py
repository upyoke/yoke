"""Closed stdout parsing for the dedicated Test Mac reset receipt."""

from __future__ import annotations

from collections.abc import Mapping

from pathlib import PurePosixPath

from yoke_harness.ssh_mac_full_reset_contract import (
    FULL_DISK_ACCESS_PROBE_PATH,
    FULL_RESET_MARKER,
    FULL_RESET_REMOTE_PATH,
    FullResetPathContract,
    PRESERVED_HOME_ENTRIES,
    RESET_ABSENT_KINDS,
    RESET_ABSENT_PATH_PREFIX,
    RESET_ABSENT_RECOVERY,
    RESET_FAILURE_PREFIX,
    RESET_LOAD_AVERAGE_PREFIX,
    RESET_PHASES,
    RESET_PROCESS_REAPED_PREFIX,
    RESET_RECOVERY_FAILURE_MARKER,
    RESET_RESTORED_ENTRIES_PREFIX,
    RESET_RESTORE_UNRESTORED_PREFIX,
    SELF_HOST_COMPOSE_PROJECT,
    RESET_SELF_HOST_CONTAINERS_PREFIX,
    RESET_SELF_HOST_IMAGES_PREFIX,
    RESET_SELF_HOST_VOLUMES_PREFIX,
    YOKE_ABSENT_RELATIVE_DIRECTORIES,
    YOKE_ABSENT_TEMP_FILES,
)


_COUNT_PREFIXES = {
    RESET_RESTORED_ENTRIES_PREFIX: "restored_entries",
    RESET_PROCESS_REAPED_PREFIX: "reaped_processes",
    RESET_SELF_HOST_CONTAINERS_PREFIX: "self_host_containers_removed",
    RESET_SELF_HOST_VOLUMES_PREFIX: "self_host_volumes_removed",
    RESET_SELF_HOST_IMAGES_PREFIX: "self_host_images_removed",
}
#: One line per counted outcome, plus the load average and the closing marker.
_RECEIPT_LINE_COUNT = len(_COUNT_PREFIXES) + 2
_UNRESTORED_NAME_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)


def unrestored_detail(detail: str) -> dict[str, object] | None:
    """Parse the captured entries a stopped restore could not return."""
    body = detail.removeprefix(RESET_RESTORE_UNRESTORED_PREFIX)
    count, _separator, names = body.partition(" ")
    if not count.isdigit():
        return None
    entries = tuple(name for name in names.split(" ") if name)
    if any(set(entry) - _UNRESTORED_NAME_CHARACTERS for entry in entries):
        return None
    return {"unrestored_entry_count": int(count), "unrestored_entries": list(entries)}


def absent_path_detail(detail: str) -> dict[str, str] | None:
    """Parse the declared-absent temp path a clear or verify still found."""
    body = detail.removeprefix(RESET_ABSENT_PATH_PREFIX)
    kind, separator, path = body.partition(" ")
    selected = PurePosixPath(path)
    if (
        not separator
        or kind not in RESET_ABSENT_KINDS
        or not selected.is_absolute()
        or ".." in selected.parts
        or path != str(selected)
    ):
        return None
    return {
        "path": path,
        "reason": kind,
        "recovery": RESET_ABSENT_RECOVERY[kind].format(path=path),
    }


def closed_outcomes(stdout: str) -> dict[str, str | int | float] | None:
    """Parse the counted success receipt the restore program emits."""
    lines = tuple(line.strip() for line in stdout.splitlines() if line.strip())
    counts: dict[str, int] = {}
    load_average: str | None = None
    for line in lines:
        if line == FULL_RESET_MARKER:
            continue
        if line.startswith(RESET_LOAD_AVERAGE_PREFIX):
            load_average = line.removeprefix(RESET_LOAD_AVERAGE_PREFIX)
            continue
        matched = False
        for prefix, field in _COUNT_PREFIXES.items():
            if not line.startswith(prefix):
                continue
            try:
                counts[field] = int(line.removeprefix(prefix))
            except ValueError:
                return None
            matched = True
            break
        if not matched:
            return None
    if (
        len(lines) != _RECEIPT_LINE_COUNT
        or lines.count(FULL_RESET_MARKER) != 1
        or set(counts) != set(_COUNT_PREFIXES.values())
        or not load_average
    ):
        return None
    try:
        load_value = float(load_average)
    except ValueError:
        return None
    if counts["restored_entries"] < 1:
        return None
    return {**counts, "load_average": load_value}


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
    if detail is not None and detail.startswith(RESET_RESTORE_UNRESTORED_PREFIX):
        if unrestored_detail(detail) is None:
            return None
    elif detail is not None and detail.startswith(RESET_ABSENT_PATH_PREFIX):
        if absent_path_detail(detail) is None:
            return None
    elif detail is not None and not recovery_failed:
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
    *,
    golden_baseline_path: str,
) -> dict[str, object]:
    """Build the success evidence document from a closed receipt."""
    home = contract.home
    rows: list[dict[str, str]] = [
        {"path": golden_baseline_path, "outcome": "restored"},
        {"path": FULL_DISK_ACCESS_PROBE_PATH, "outcome": "readable"},
    ]
    rows.extend(
        {"path": f"{home}/{suffix}", "outcome": "preserved"}
        for suffix in PRESERVED_HOME_ENTRIES
    )
    rows.extend(
        {"path": f"{home}/{suffix}", "outcome": "absent"}
        for suffix in YOKE_ABSENT_RELATIVE_DIRECTORIES
    )
    rows.extend(
        {"path": path, "outcome": "absent"} for path in contract.tool_file_paths
    )
    rows.extend({"path": path, "outcome": "absent"} for path in YOKE_ABSENT_TEMP_FILES)
    rows.extend(
        {"path": path, "outcome": "restored-from-baseline"}
        for path in contract.startup_files
    )
    rows.extend(
        (
            {"path": contract.tool_bin_dir, "outcome": "carries-no-yoke-tool"},
            {
                "path": contract.shell_path,
                "outcome": "login-and-ssh-resolution-clean",
            },
            {"path": FULL_RESET_REMOTE_PATH, "outcome": "removed"},
        )
    )
    return {
        "paths": rows,
        "baseline_state": {
            "golden_baseline_path": golden_baseline_path,
            "restored_entries": outcomes["restored_entries"],
            "preserved_entries": list(PRESERVED_HOME_ENTRIES),
        },
        "path_state": {
            "launcher": contract.launcher_path,
            "launcher_present": False,
            "tool_bin_dir": contract.tool_bin_dir,
            # The restored host proves no Yoke tool resolves. It deliberately
            # does not claim the tool directory is off the PATH, because the
            # user's own tools legitimately live there.
            "yoke_tools_resolve": False,
        },
        "process_state": {
            "reaped_processes": outcomes["reaped_processes"],
            "surviving_matches": 0,
            "load_average": outcomes["load_average"],
        },
        "self_host_state": {
            "compose_project": SELF_HOST_COMPOSE_PROJECT,
            "containers_removed": outcomes["self_host_containers_removed"],
            "volumes_removed": outcomes["self_host_volumes_removed"],
            "images_removed": outcomes["self_host_images_removed"],
            "stack_reachable": False,
        },
    }


__all__ = [
    "absent_path_detail",
    "closed_outcomes",
    "failure_outcome",
    "success_evidence",
    "unrestored_detail",
]
