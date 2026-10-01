"""Report the machine-local hook resident even when fallback warnings quieten."""

from __future__ import annotations

from typing import Any

from yoke_cli.hook_resident_client import resident_paths
from yoke_cli.hook_resident_health import resident_socket_problem
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


SLUG = "hook-resident"
TITLE = "Machine-local hook resident listener"


def hc_hook_resident(conn: Any, args: DoctorArgs, rec: RecordCollector) -> None:
    try:
        paths = resident_paths()
        problem = resident_socket_problem(paths.socket)
    except OSError as exc:
        rec.record(
            SLUG,
            TITLE,
            "WARN",
            f"YOKE_HOOK_RESIDENT_STATE_UNREADABLE: {type(exc).__name__}. "
            "Repair the machine cache directory permissions; hooks still "
            "use the canonical in-process fallback.",
        )
        return
    if problem:
        rec.record(
            SLUG,
            TITLE,
            "WARN",
            f"{problem}; hooks use the canonical in-process fallback. "
            f"Inspect {paths.log} for the startup failure; the next hook "
            "invocation retries resident startup.",
        )
        return
    rec.record(SLUG, TITLE, "PASS", f"Resident accepts connections at {paths.socket}.")
