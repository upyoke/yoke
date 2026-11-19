"""Name why a local artifact handle cannot be ingested by this control plane."""

from __future__ import annotations

from typing import Any, Optional


def local_handle_refusal(
    conn,
    *,
    req_id: int,
    run_id: int,
    handle: dict[str, Any],
) -> Optional[str]:
    """Name why a local handle cannot be ingested by this control plane."""

    from yoke_core.domain.project_checkout_locations import (
        checkout_for_project_id,
    )
    from yoke_core.domain.qa_artifact_handle import is_present
    from yoke_core.domain.qa_artifact_owner import requirement_storage_owner
    from yoke_core.domain.qa_artifacts import (
        case_artifact_subject,
        is_server_evidence_path,
    )

    if handle.get("backend") != "local":
        return None
    req_row = requirement_storage_owner(conn, int(req_id))
    recipe = (
        "Send the bytes instead so they persist in project artifact storage: "
        f"yoke qa artifact add --requirement-id {int(req_id)} --run-id "
        f"{int(run_id)} --artifact-type TYPE --content-file PATH"
    )
    if not is_server_evidence_path(
        str(handle["path"]),
        str(req_row["project"]),
        case_artifact_subject(req_row),
        int(run_id),
        checkout=checkout_for_project_id(int(req_row["project_id"])),
    ):
        return (
            f"artifact_handle names {handle['path']!r}, which this control "
            "plane cannot read. Recording a path on a client or test host "
            f"would outlive its own bytes. {recipe}"
        )
    if not is_present(handle):
        return (
            f"artifact_handle names {handle['path']!r}, which is inside this "
            "control plane's evidence storage but holds no bytes: a transfer "
            "that never arrived would be recorded as readable evidence. "
            f"{recipe}"
        )
    return None
