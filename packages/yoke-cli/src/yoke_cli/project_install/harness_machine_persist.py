"""Persist the install-written harness glue record to the control plane."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def persist_install_glue(
    repo_root: Path,
    project_id: int,
    install_report: Dict[str, Any],
) -> None:
    """Collect local evidence, stamp glue_written, and upsert. Fail-soft."""
    from yoke_cli.commands._helpers import call_dispatcher, ensure_handlers_loaded
    from yoke_cli.project_install.hook_trust_report import harness_ids_written
    from yoke_cli.transport.dispatcher import build_actor
    from yoke_cli.project_install.harness_inventory import (
        collect_harness_inventory,
        collect_pack_prerequisite_inventory,
    )
    from yoke_contracts.api.function_call import TargetRef

    reports = collect_harness_inventory(repo_root)
    written = set(harness_ids_written(install_report))
    by_id = {str(row["harness_id"]): dict(row) for row in reports}
    for harness_id in written:
        row = by_id.setdefault(
            harness_id,
            {
                "harness_id": harness_id,
                "glue_present": False,
                "glue_malformed": False,
                "config_present": False,
                "project_entry_present": False,
                "approval_state": "unknown",
            },
        )
        row["glue_written"] = True
    payload_reports: List[Dict[str, Any]] = list(by_id.values())
    if not payload_reports:
        return
    ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="harness.machine_report.upsert",
        target=TargetRef(kind="global"),
        payload={
            "project_id": int(project_id),
            "reports": payload_reports,
            "pack_prerequisites": collect_pack_prerequisite_inventory(repo_root),
        },
        actor=build_actor(session_id=None),
    )
    if not response.success:
        message = (
            response.error.message
            if response.error is not None
            else "harness.machine_report.upsert failed"
        )
        install_report.setdefault("warnings", []).append(
            f"harness machine report was not persisted: {message}"
        )
