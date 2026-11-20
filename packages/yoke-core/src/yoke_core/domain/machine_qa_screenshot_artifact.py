"""Validate and retain desktop evidence under its issued machine lease."""

from __future__ import annotations

import hashlib

from yoke_contracts.machine_screenshot import screenshot_png
from yoke_core.domain.qa_artifact_storage import store_owned_artifact_bytes


def validate_screenshot(parsed) -> None:
    """A successful receipt must carry exactly the nonblank PNG it describes."""
    if "artifact_handle" in parsed.checks[0]:
        raise ValueError("screenshot artifact handles are assigned by the authority")
    if parsed.status == "error":
        if parsed.artifacts or parsed.checks[0].get("artifact_token"):
            raise ValueError("failed screenshot cannot carry a capture artifact")
        return
    if len(parsed.artifacts) != 1:
        raise ValueError("screenshot result requires exactly one PNG artifact")
    artifact = parsed.artifacts[0]
    row = parsed.checks[0]
    if (
        artifact.token != row.get("artifact_token")
        or artifact.content_type != "image/png"
    ):
        raise ValueError(
            "screenshot artifact must match its receipt token and PNG type"
        )
    content, size = screenshot_png(artifact.content_base64)
    if list(size) != [row.get("width"), row.get("height")]:
        raise ValueError("screenshot dimensions differ from its receipt")
    if row.get("sha256") != hashlib.sha256(content).hexdigest():
        raise ValueError("screenshot bytes differ from its receipt digest")


def replay_screenshot_checks(checks, recorded_checks):
    """Use the issued handle for comparison without changing the submission."""
    row = dict(checks[0])
    row.pop("artifact_token", None)
    if "artifact_handle" in recorded_checks[0]:
        row["artifact_handle"] = recorded_checks[0]["artifact_handle"]
    return [row]


def store_screenshot(conn, parsed, contract, *, borrowed_turn: bool) -> None:
    """Use the project's normal QA artifact store, then persist only its handle."""
    if parsed.status != "verified":
        return
    artifact = parsed.artifacts[0]
    content, _size = screenshot_png(artifact.content_base64)
    machine = contract.settings["resource_name"]
    # A borrowed lease can accept a later capture. Keep each image addressable
    # so replacing the receipt cannot overwrite bytes referenced by an old one.
    filename = (
        f"desktop-{parsed.checks[0]['sha256']}.png" if borrowed_turn else "desktop.png"
    )
    handle = store_owned_artifact_bytes(
        conn,
        owner={
            "project_id": contract.project_id,
            "project": contract.project,
            "target_env": None,
            "artifact_subject": "test-machine-" + machine,
        },
        run_id=contract.lease_id,
        filename=filename,
        content=content,
        content_type="image/png",
    )
    parsed.checks[0].pop("artifact_token")
    parsed.checks[0]["artifact_handle"] = handle
