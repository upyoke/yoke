"""Authorized reads of durable and explicitly machine-local QA evidence."""

from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from fastapi.testclient import TestClient

from runtime.api.auth_test_helpers import mint_api_auth_context
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
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.s3_presign import AwsCredentials
from yoke_core.domain.yoke_function_registry import reset_registry_for_tests


_CREDS = AwsCredentials(
    access_key_id="AKIDEXAMPLE",
    secret_access_key="secret",
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


def _seed_s3_configuration(conn, *, bucket: str) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sites ("
        "id TEXT PRIMARY KEY, project_id INTEGER NOT NULL, name TEXT NOT NULL,"
        "description TEXT, created_at TEXT NOT NULL, settings TEXT DEFAULT '{}')"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS environments ("
        "id TEXT PRIMARY KEY, site TEXT NOT NULL, name TEXT NOT NULL,"
        "url TEXT, deploy_method TEXT, deploy_command TEXT,"
        "health_check_url TEXT, config_notes TEXT, last_deployed_at TEXT,"
        "created_at TEXT NOT NULL, settings TEXT DEFAULT '{}')"
    )
    conn.execute(
        "INSERT INTO sites (id, project_id, name, created_at) "
        "VALUES ('site-1', 1, 'core', '2026-07-28T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO environments (id, site, name, settings, created_at) "
        "VALUES ('env-prod', 'site-1', 'prod', %s, "
        "'2026-07-28T00:00:00Z')",
        (json.dumps({"artifacts": {"bucket": bucket}}),),
    )
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings) "
        "VALUES (1, 'aws-admin', %s)",
        (json.dumps({"region": "us-east-1"}),),
    )
    conn.commit()


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
                "yoke_core.domain.project_checkout_locations.checkout_for_project_id",
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
    assert (
        base64.b64decode(
            outcome.result_payload["content_base64"],
        )
        == b"full captured output"
    )


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
                "yoke_core.domain.project_checkout_locations.checkout_for_project_id",
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


def test_s3_evidence_returns_authorized_presigned_download() -> None:
    bucket = "yoke-prod-artifacts"
    key = "qa-artifacts/yoke/42/1/output.txt"
    with test_database() as conn:
        artifact_id = _seed_artifact(
            conn,
            handle={"backend": "s3", "bucket": bucket, "key": key},
        )
        _seed_s3_configuration(conn, bucket=bucket)
        with patch(
            "yoke_core.domain.handlers.qa_artifact_presign._capability_credentials",
            return_value=_CREDS,
        ):
            outcome = handle_qa_artifact_read(_request(10, artifact_id))

    assert outcome.primary_success
    result = outcome.result_payload
    assert result["backend"] == "s3"
    assert result["disposition"] == "ready"
    assert result["expires_in_s"] == 300
    parts = urlsplit(result["download_url"])
    assert parts.netloc == f"{bucket}.s3.us-east-1.amazonaws.com"
    assert parts.path == f"/{key}"
    query = parse_qs(parts.query)
    assert query["X-Amz-Expires"] == ["300"]
    assert "X-Amz-Signature" in query


def test_s3_read_matches_real_http_function_boundary() -> None:
    from yoke_core.api.main import app

    bucket = "yoke-prod-artifacts"
    key = "qa-artifacts/yoke/42/1/output.txt"
    reset_registry_for_tests()
    register_all_handlers()
    try:
        with test_database() as conn:
            artifact_id = _seed_artifact(
                conn,
                handle={"backend": "s3", "bucket": bucket, "key": key},
            )
            _seed_s3_configuration(conn, bucket=bucket)
            auth = mint_api_auth_context(conn)
            client = TestClient(app)
            client.headers.update(auth.headers)
            with patch(
                "yoke_core.domain.handlers.qa_artifact_presign._capability_credentials",
                return_value=_CREDS,
            ):
                response = client.post(
                    "/v1/functions/call",
                    json=_request(10, artifact_id).model_dump(mode="json"),
                )
    finally:
        reset_registry_for_tests()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"], body.get("error")
    result = body["result"]
    assert result["backend"] == "s3"
    assert result["disposition"] == "ready"
    assert result["expires_in_s"] == 300
    assert urlsplit(result["download_url"]).path == f"/{key}"


def test_local_read_matches_real_http_function_boundary(tmp_path) -> None:
    from yoke_core.api.main import app

    evidence = tmp_path / "qa-output.txt"
    evidence.write_bytes(b"full captured output")
    reset_registry_for_tests()
    register_all_handlers()
    try:
        with test_database() as conn:
            artifact_id = _seed_artifact(
                conn,
                handle={"backend": "local", "path": str(evidence)},
            )
            auth = mint_api_auth_context(conn)
            client = TestClient(app)
            client.headers.update(auth.headers)
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
                response = client.post(
                    "/v1/functions/call",
                    json=_request(10, artifact_id).model_dump(mode="json"),
                )
    finally:
        reset_registry_for_tests()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"], body.get("error")
    result = body["result"]
    assert result["backend"] == "local"
    assert result["disposition"] == "ready"
    assert base64.b64decode(result["content_base64"]) == b"full captured output"


def test_artifact_read_refuses_a_different_requirement() -> None:
    with test_database() as conn:
        artifact_id = _seed_artifact(
            conn,
            handle={"backend": "local", "path": "qa-output.txt"},
        )
        outcome = handle_qa_artifact_read(_request(999, artifact_id))

    assert not outcome.primary_success
    assert outcome.error.code == "target_invalid"
