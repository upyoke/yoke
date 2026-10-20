"""Report the machine-local hook resident even when fallback warnings quieten."""

from __future__ import annotations

from typing import Any

from yoke_cli.hook_resident_client import resident_paths
from yoke_cli.hook_resident_health import resident_revision_problem
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


SLUG = "hook-resident"
TITLE = "Machine-local hook resident listener"


def hc_hook_resident(conn: Any, args: DoctorArgs, rec: RecordCollector) -> None:
    try:
        paths = resident_paths()
        from yoke_contracts.execution_provenance import collect_execution_provenance

        problem = resident_revision_problem(
            paths.socket, collect_execution_provenance()["source_sha"]
        )
    except OSError as exc:
        rec.record(
            SLUG,
            TITLE,
            "FAIL",
            f"YOKE_HOOK_RESIDENT_STATE_UNREADABLE: {type(exc).__name__}. "
            "Repair the machine cache directory permissions, then run "
            "yoke hook resident restart.",
        )
        return
    if problem:
        rec.record(
            SLUG,
            TITLE,
            "FAIL",
            f"{problem}. Run yoke hook resident restart to start the installed "
            f"build and prove it answers; if that fails, inspect {paths.log}.",
        )
        return
    rec.record(SLUG, TITLE, "PASS", "Resident runs the installed build.")
