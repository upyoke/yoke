"""Where a golden capture writes, and how the machine learns about it.

A capture never overwrites the baseline it was taken beside. A failed capture
over the live golden leaves a machine with no baseline at all, and a successful
one silently retires a directory another host may still be restoring from, so
the default destination is a new timestamped directory next to the current one and
the settings record it only once the capture has succeeded.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Mapping

from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError,
    validate_golden_baseline_path,
)
from yoke_contracts.machine_qa_host_control import (
    GOLDEN_CAPTURE_OPERATION,
    KEPT_GOLDEN_PATHS_KEY,
    KEPT_GOLDEN_PATHS_UNKNOWN_KEY,
    REGISTERED_GOLDENS_KEY,
    VERIFY_OPERATION,
)

from yoke_core.domain.machine_qa_capability_rows import (
    TestMachineCapabilityRow,
    select_test_machine_row,
    test_machine_capability_rows,
)
from yoke_core.domain.machine_qa_shared_home import (
    leased_shared_home,
    shared_home_registrations,
)
from yoke_core.domain.project_identity import resolve_project


GOLDEN_BASELINE_PATH_KEY = "golden_baseline_path"


def selected_test_machine_row(
    conn: Any,
    *,
    project: str,
    test_machine: str | None,
) -> TestMachineCapabilityRow:
    """Return the one machine a project-and-name pair addresses."""
    identity = resolve_project(conn, project, required=False)
    if identity is None:
        raise TestMachineCapabilityError(f"project {project!r} not found")
    return select_test_machine_row(
        test_machine_capability_rows(conn, project_id=identity.id),
        project=identity.slug,
        test_machine=test_machine,
    )


def timestamped_golden_directory_name(user: str) -> str:
    """Name a new golden with the current UTC second for capture and refresh."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{user}-home-{stamp}"


def resolve_golden_capture_destination(
    row: TestMachineCapabilityRow,
    *,
    requested: str | None = None,
) -> str:
    """Return the absolute directory this capture writes, or refuse to guess."""
    if requested:
        return validate_golden_baseline_path(requested)
    declared = row.settings.get(GOLDEN_BASELINE_PATH_KEY)
    if not declared:
        raise TestMachineCapabilityError(
            f"test machine {row.test_machine!r} declares no {GOLDEN_BASELINE_PATH_KEY}, "
            "so there is nowhere to put a capture beside; pass an absolute "
            "--destination for the first golden baseline"
        )
    parent = PurePosixPath(validate_golden_baseline_path(declared)).parent
    candidate = str(parent / timestamped_golden_directory_name(row.settings["user"]))
    if candidate == declared:
        raise TestMachineCapabilityError(
            f"golden_capture_destination_collision: {declared} already names "
            f"the current golden for {row.test_machine!r}; retry after the UTC "
            "second changes or pass a different explicit --destination"
        )
    return validate_golden_baseline_path(candidate)


def record_captured_golden_baseline(
    conn: Any,
    row: TestMachineCapabilityRow,
    *,
    destination: str,
) -> bool:
    """Point the machine at the baseline a capture just produced.

    Deliberately narrower than a settings replace: this records a fact the
    server just proved, so it must not reset the machine's verification the way
    an operator's settings edit does.
    """
    if row.settings.get(GOLDEN_BASELINE_PATH_KEY) == destination:
        return False
    from yoke_core.domain.machine_qa_proven_settings import replace_proven_settings

    changed = replace_proven_settings(
        conn, row, {GOLDEN_BASELINE_PATH_KEY: destination}
    )
    if not changed:
        raise TestMachineCapabilityError(
            f"test machine {row.test_machine!r} settings changed while its golden "
            "baseline was being captured; re-read the machine and record "
            f"{destination} as its {GOLDEN_BASELINE_PATH_KEY}"
        )
    return True


def kept_golden_fields(
    conn: Any,
    *,
    settings: Mapping[str, str],
    destination: str | None,
) -> dict[str, Any]:
    """Name every registered golden beside a capture so retention keeps it.

    Several projects can register the same host and user, each with its own
    golden in the same parent. Retention runs on the operator's machine and
    can only see the capturing project, so the server names every golden
    registered for this host and user in that parent. A registration it cannot
    read, or another name for this home that is leased now, makes the answer
    unknown rather than incomplete.
    """
    if not destination:
        return {}
    parent = PurePosixPath(destination).parent
    try:
        rows = shared_home_registrations(conn, settings)
    except TestMachineCapabilityError as exc:
        return {
            KEPT_GOLDEN_PATHS_UNKNOWN_KEY: (
                f"a stored test machine is unreadable, so the goldens sharing "
                f"this home are unknown ({exc})"
            )
        }
    leased = leased_shared_home(conn, rows, test_machine=settings["resource_name"])
    if leased is not None:
        return {KEPT_GOLDEN_PATHS_UNKNOWN_KEY: leased}
    kept = {destination}
    for row in rows:
        path = row.settings.get(GOLDEN_BASELINE_PATH_KEY)
        if path and PurePosixPath(path).parent == parent:
            kept.add(path)
    return {KEPT_GOLDEN_PATHS_KEY: sorted(kept)}


def registered_golden_fields(conn: Any, settings: Mapping[str, str]) -> dict[str, Any]:
    """Name every golden registered for this host and user, for verify to find."""
    return {
        REGISTERED_GOLDENS_KEY: [
            {
                "project": row.project,
                "test_machine": row.test_machine,
                "path": row.settings[GOLDEN_BASELINE_PATH_KEY],
            }
            for row in shared_home_registrations(conn, settings)
            if row.settings.get(GOLDEN_BASELINE_PATH_KEY)
        ]
    }


def operation_golden_inputs(
    conn: Any,
    *,
    project: str,
    test_machine: str | None,
    operation: str,
    destination: str | None,
) -> tuple[str | None, dict[str, Any]]:
    """Resolve a capture's destination, or name the goldens a verify checks."""
    if operation not in (GOLDEN_CAPTURE_OPERATION, VERIFY_OPERATION):
        return destination, {}
    row = selected_test_machine_row(conn, project=project, test_machine=test_machine)
    if operation == VERIFY_OPERATION:
        return destination, registered_golden_fields(conn, row.settings)
    return resolve_golden_capture_destination(row, requested=destination), {}


__all__ = [
    "GOLDEN_BASELINE_PATH_KEY",
    "kept_golden_fields",
    "operation_golden_inputs",
    "registered_golden_fields",
    "selected_test_machine_row",
    "timestamped_golden_directory_name",
    "record_captured_golden_baseline",
    "resolve_golden_capture_destination",
]
