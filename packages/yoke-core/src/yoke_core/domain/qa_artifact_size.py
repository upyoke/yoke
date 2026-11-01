"""Measure submitted S3 objects through their configured credential owner."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.qa_artifact_broker import broker_config, presign_with_broker
from yoke_core.domain.qa_artifacts import case_artifact_subject
from yoke_core.domain.universe_artifact_store import handle_size as stored_handle_size
from yoke_core.domain.signed_object_transfer import signed_object_size


def handle_size(conn: Any, owner: dict, run_id: int, handle: dict) -> int:
    """Hosted engines use their signer; other installs use machine credentials."""
    broker = broker_config()
    if broker is not None:
        signed = presign_with_broker(
            broker,
            operation="get",
            project=str(owner["project"]),
            subject=owner.get("artifact_subject") or case_artifact_subject(owner),
            run_id=run_id,
            filename=str(handle["key"]).rsplit("/", 1)[-1],
        )
        if (signed.bucket, signed.key) != (handle["bucket"], handle["key"]):
            raise ValueError("submitted handle differs from the signer-owned object")
        return signed_object_size(signed.url, bucket=signed.bucket, key=signed.key)
    from yoke_core.domain.handlers.qa_artifact_presign import _aws_region

    return stored_handle_size(
        handle,
        project=str(owner["project"]),
        store={"region": _aws_region(conn, int(owner["project_id"]))},
    )
