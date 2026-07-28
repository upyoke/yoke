"""Authorized reads of durable and explicitly machine-local QA evidence."""

from __future__ import annotations

import base64
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from runtime.api.auth_test_helpers import mint_api_auth_context
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.qa_artifact_read_test_support import (
    CREDS,
    artifact_read_request,
    seed_artifact,
    seed_deployment_artifact,
    seed_s3_configuration,
)
from yoke_core.domain.handlers.qa_artifact_read import (
    handle_qa_artifact_read,
)
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.yoke_function_registry import reset_registry_for_tests


def test_local_evidence_inside_checkout_is_returned_inline(tmp_path) -> None:
    evidence = tmp_path / "qa-output.txt"
    evidence.write_bytes(b"full captured output")
    with test_database() as conn:
        artifact_id = seed_artifact(
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
            outcome = handle_qa_artifact_read(artifact_read_request(10, artifact_id))

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
        artifact_id = seed_artifact(
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
            outcome = handle_qa_artifact_read(artifact_read_request(10, artifact_id))

    assert outcome.primary_success
    assert outcome.result_payload["disposition"] == "evidence_on_machine"
    assert outcome.result_payload["machine"] == "Test Mac"
    assert "content_base64" not in outcome.result_payload


def test_deployment_run_local_evidence_is_read_from_its_subject_root(
    tmp_path,
) -> None:
    evidence = tmp_path / "deployment-output.txt"
    evidence.write_bytes(b"deployment proof")
    with test_database() as conn:
        artifact_id = seed_deployment_artifact(
            conn,
            handle={"backend": "local", "path": str(evidence)},
        )
        requirement_id = int(
            conn.execute(
                "SELECT qa_requirement_id FROM qa_runs "
                "WHERE id=(SELECT qa_run_id FROM qa_artifacts WHERE id=%s)",
                (artifact_id,),
            ).fetchone()[0]
        )
        with (
            patch(
                "yoke_core.domain.project_checkout_locations.checkout_for_project_id",
                return_value=tmp_path,
            ),
            patch(
                "yoke_core.domain.qa_artifacts.artifact_directory",
                return_value=tmp_path / ".qa",
            ) as artifact_root,
        ):
            outcome = handle_qa_artifact_read(
                artifact_read_request(requirement_id, artifact_id)
            )

    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["disposition"] == "ready"
    assert (
        base64.b64decode(outcome.result_payload["content_base64"])
        == b"deployment proof"
    )
    assert artifact_root.call_args.args[1] == ("deployment-run-run-20260728-903")


def test_s3_evidence_returns_authorized_presigned_download() -> None:
    bucket = "yoke-prod-artifacts"
    key = "qa-artifacts/yoke/42/1/output.txt"
    with test_database() as conn:
        artifact_id = seed_artifact(
            conn,
            handle={"backend": "s3", "bucket": bucket, "key": key},
        )
        seed_s3_configuration(conn, bucket=bucket)
        with patch(
            "yoke_core.domain.handlers.qa_artifact_presign._capability_credentials",
            return_value=CREDS,
        ):
            outcome = handle_qa_artifact_read(artifact_read_request(10, artifact_id))

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
            artifact_id = seed_artifact(
                conn,
                handle={"backend": "s3", "bucket": bucket, "key": key},
            )
            seed_s3_configuration(conn, bucket=bucket)
            auth = mint_api_auth_context(conn)
            client = TestClient(app)
            client.headers.update(auth.headers)
            with patch(
                "yoke_core.domain.handlers.qa_artifact_presign._capability_credentials",
                return_value=CREDS,
            ):
                response = client.post(
                    "/v1/functions/call",
                    json=artifact_read_request(10, artifact_id).model_dump(mode="json"),
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
            artifact_id = seed_artifact(
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
                    json=artifact_read_request(10, artifact_id).model_dump(mode="json"),
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
        artifact_id = seed_artifact(
            conn,
            handle={"backend": "local", "path": "qa-output.txt"},
        )
        outcome = handle_qa_artifact_read(artifact_read_request(999, artifact_id))

    assert not outcome.primary_success
    assert outcome.error.code == "target_invalid"
