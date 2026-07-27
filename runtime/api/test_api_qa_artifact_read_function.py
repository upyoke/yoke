"""Authorized reads of durable and explicitly machine-local QA evidence."""

from __future__ import annotations

import base64
import json
from unittest.mock import patch

from runtime.api.fixtures.backlog_inserts import (
    insert_item,
    insert_qa_requirement,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.qa_artifact_read import (
    handle_qa_artifact_read,
)


def _request(requirement_id: int, artifact_id: int) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="qa.artifact.read",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=requirement_id,
        ),
        payload={"artifact_id": artifact_id},
    )


def _seed_artifact(
    conn,
    *,
    handle: dict,
    metadata: dict | None = None,
) -> int:
    insert_item(conn, id=42, title="Evidence owner")
    insert_qa_requirement(
        conn,
        id=10,
        item_id=42,
        qa_kind="command",
        qa_phase="verification",
        blocking_mode="blocking",
    )
    run = conn.execute(
        "INSERT INTO qa_runs("
        "qa_requirement_id, executor_type, qa_kind, verdict, created_at"
        ") VALUES (10, 'worktree_run', 'command', 'pass', "
        "'2026-07-26T12:00:00Z') RETURNING id",
    ).fetchone()
    artifact = conn.execute(
        "INSERT INTO qa_artifacts("
        "qa_run_id, artifact_type, content_type, artifact_handle, metadata, "
        "created_at"
        ") VALUES (%s, 'output', 'text/plain', %s, %s, "
        "'2026-07-26T12:00:00Z') RETURNING id",
        (
            run["id"],
            json.dumps(handle),
            json.dumps(metadata or {}),
        ),
    ).fetchone()
    conn.commit()
    return int(artifact["id"])


def test_local_evidence_inside_checkout_is_returned_inline(tmp_path) -> None:
    evidence = tmp_path / "qa-output.txt"
    evidence.write_bytes(b"full captured output")
    with test_database() as conn:
        artifact_id = _seed_artifact(
            conn,
            handle={"backend": "local", "path": str(evidence)},
        )
        with (
            patch(
                "yoke_core.domain.project_checkout_locations."
                "checkout_for_project_id",
                return_value=tmp_path,
            ),
            patch(
                "yoke_core.domain.qa_artifacts.artifact_directory",
                return_value=tmp_path / ".qa",
            ),
        ):
            outcome = handle_qa_artifact_read(_request(10, artifact_id))

    assert outcome.primary_success
    assert outcome.result_payload["disposition"] == "ready"
    assert base64.b64decode(
        outcome.result_payload["content_base64"],
    ) == b"full captured output"


def test_missing_machine_local_evidence_is_reported_honestly(tmp_path) -> None:
    with test_database() as conn:
        artifact_id = _seed_artifact(
            conn,
            handle={
                "backend": "local",
                "path": str(tmp_path / "missing.png"),
            },
            metadata={"machine": "Test Mac"},
        )
        with (
            patch(
                "yoke_core.domain.project_checkout_locations."
                "checkout_for_project_id",
                return_value=tmp_path,
            ),
            patch(
                "yoke_core.domain.qa_artifacts.artifact_directory",
                return_value=tmp_path / ".qa",
            ),
        ):
            outcome = handle_qa_artifact_read(_request(10, artifact_id))

    assert outcome.primary_success
    assert outcome.result_payload["disposition"] == "evidence_on_machine"
    assert outcome.result_payload["machine"] == "Test Mac"
    assert "content_base64" not in outcome.result_payload


def test_artifact_read_refuses_a_different_requirement() -> None:
    with test_database() as conn:
        artifact_id = _seed_artifact(
            conn,
            handle={"backend": "local", "path": "qa-output.txt"},
        )
        outcome = handle_qa_artifact_read(_request(999, artifact_id))

    assert not outcome.primary_success
    assert outcome.error.code == "target_invalid"
