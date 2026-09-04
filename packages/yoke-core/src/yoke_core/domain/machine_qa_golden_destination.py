"""Where a golden capture writes, and how the machine learns about it.

A capture never overwrites the baseline it was taken beside. A failed capture
over the live golden leaves a machine with no baseline at all, and a successful
one silently retires a directory another host may still be restoring from, so
the default destination is a new dated directory next to the current one and
the settings record it only once the capture has succeeded.
"""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any

from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError,
    validate_golden_baseline_path,
    validate_test_machine_settings,
)

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.machine_qa_capability_rows import (
    TestMachineCapabilityRow,
    select_test_machine_row,
    test_machine_capability_rows,
)
from yoke_core.domain.project_identity import resolve_project


GOLDEN_BASELINE_PATH_KEY = "golden_baseline_path"


def selected_test_machine_row(
    conn: Any,
    *,
    project: str,
    machine: str | None,
) -> TestMachineCapabilityRow:
    """Return the one machine a project-and-name pair addresses."""
    identity = resolve_project(conn, project, required=False)
    if identity is None:
        raise TestMachineCapabilityError(f"project {project!r} not found")
    return select_test_machine_row(
        test_machine_capability_rows(conn, project_id=identity.id),
        project=identity.slug,
        machine=machine,
    )


def dated_golden_directory_name(user: str, *, today: str) -> str:
    """Return the directory name a capture taken today writes into."""
    return f"{user}-home-{today.replace('-', '')}"


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
            f"test machine {row.machine!r} declares no {GOLDEN_BASELINE_PATH_KEY}, "
            "so there is nowhere to put a capture beside; pass an absolute "
            "--destination for the first golden baseline"
        )
    parent = PurePosixPath(validate_golden_baseline_path(declared)).parent
    candidate = str(
        parent
        / dated_golden_directory_name(
            row.settings["user"],
            today=iso8601_now()[:10],
        )
    )
    if candidate == declared:
        raise TestMachineCapabilityError(
            f"{declared} is already today's capture destination for "
            f"{row.machine!r}; pass an explicit --destination to capture a "
            "second baseline on the same day"
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
    document = validate_test_machine_settings(
        {**row.settings, GOLDEN_BASELINE_PATH_KEY: destination}
    )
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    updated = conn.execute(
        f"UPDATE project_capabilities SET settings={marker} "
        f"WHERE project_id={marker} AND type={marker} AND "
        f"COALESCE(settings,'{{}}')={marker}",
        (
            json.dumps(document, separators=(",", ":"), sort_keys=True),
            row.project_id,
            row.capability_type,
            row.settings_token,
        ),
    )
    changed = getattr(updated, "rowcount", 1)
    if changed is not None and int(changed) < 1:
        raise TestMachineCapabilityError(
            f"test machine {row.machine!r} settings changed while its golden "
            "baseline was being captured; re-read the machine and record "
            f"{destination} as its {GOLDEN_BASELINE_PATH_KEY}"
        )
    return True


__all__ = [
    "GOLDEN_BASELINE_PATH_KEY",
    "selected_test_machine_row",
    "dated_golden_directory_name",
    "record_captured_golden_baseline",
    "resolve_golden_capture_destination",
]
