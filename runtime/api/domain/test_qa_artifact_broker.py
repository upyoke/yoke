"""Hosted tenant QA-evidence broker consumer contract."""

from __future__ import annotations

import base64
import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.qa_artifact_read_test_support import artifact_read_request
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain import qa_artifact_broker as broker
from yoke_core.domain.handlers.qa_artifact_add import handle_qa_artifact_add
from yoke_core.domain.handlers.qa_artifact_presign import handle_qa_artifact_presign
from yoke_core.domain.handlers.qa_artifact_read import handle_qa_artifact_read
from yoke_core.domain.handlers.qa_browser_writes import handle_qa_run_add


def _broker_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    token = tmp_path / "broker.token"
    token.write_text("tenant-service-token\n", encoding="utf-8")
    values = {
        broker.BUCKET_ENV: "yoke-prod-artifacts",
        broker.PREFIX_ENV: "tenants/7",
        broker.BROKER_URL_ENV: "http://host.docker.internal:8601/tenant/qa-artifacts/presign",
        broker.TOKEN_FILE_ENV: str(token),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return token


def _request(function: str, requirement_id: int, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(
            kind="qa_requirement", qa_requirement_id=requirement_id
        ),
        payload=payload,
    )


def _seed_run(conn) -> int:
    insert_item(conn, id=42, title="T", status="reviewing-implementation")
    insert_qa_requirement(
        conn,
        id=10,
        item_id=42,
        qa_kind="plan_case",
        qa_phase="verification",
        blocking_mode="blocking",
        success_policy="{}",
        method_id="browser-check",
    )
    with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
        outcome = handle_qa_run_add(
            _request("qa.run.add", 10, {"performed_by": "browser_substrate"})
        )
    assert outcome.primary_success, outcome.error
    return int(outcome.result_payload["qa_run_id"])


def _signed(operation: str, run_id: int, filename: str) -> broker.BrokerPresign:
    method = "PUT" if operation == "put" else "GET"
    return broker.BrokerPresign(
        url=f"https://s3.example/{operation}",
        method=method,
        bucket="yoke-prod-artifacts",
        key=f"tenants/7/qa-artifacts/yoke/42/{run_id}/{filename}",
        expires_in=900,
    )


def test_broker_config_refuses_partial_publication() -> None:
    assert broker.broker_config({broker.BUCKET_ENV: "direct-store"}) is None
    with pytest.raises(broker.ArtifactBrokerError) as raised:
        broker.broker_config({broker.BROKER_URL_ENV: "http://broker/presign"})
    assert raised.value.code == "artifact_broker_configuration_invalid"
    assert broker.PREFIX_ENV in str(raised.value)


def test_broker_request_uses_token_and_validates_server_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _broker_env(monkeypatch, tmp_path)
    config = broker.broker_config()
    assert config is not None
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit: int) -> bytes:
            return json.dumps(
                {
                    "url": "https://s3.example/upload",
                    "method": "PUT",
                    "bucket": config.bucket,
                    "key": "tenants/7/qa-artifacts/yoke/42/5/shot.png",
                    "expires_in": 900,
                }
            ).encode("utf-8")

    def open_request(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(broker.urllib.request, "urlopen", open_request)
    result = broker.presign_with_broker(
        config,
        operation="put",
        project="yoke",
        subject=42,
        run_id=5,
        filename="shot.png",
    )
    request = captured["request"]
    assert request.full_url == config.url
    assert request.get_header("Authorization") == "Bearer tenant-service-token"
    assert json.loads(request.data) == {
        "operation": "put",
        "project": "yoke",
        "subject": "42",
        "run_id": 5,
        "filename": "shot.png",
    }
    assert captured["timeout"] == 30
    assert result.key.startswith("tenants/7/qa-artifacts/")
    assert token.read_text(encoding="utf-8").strip() not in repr(result)


def test_broker_response_cannot_redirect_to_foreign_tenant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _broker_env(monkeypatch, tmp_path)
    config = broker.broker_config()
    assert config is not None

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit: int) -> bytes:
            return json.dumps(
                {
                    "url": "https://s3.example/upload",
                    "method": "PUT",
                    "bucket": config.bucket,
                    "key": "tenants/8/qa-artifacts/yoke/42/5/shot.png",
                    "expires_in": 900,
                }
            ).encode("utf-8")

    monkeypatch.setattr(broker.urllib.request, "urlopen", lambda *_a, **_k: Response())
    with pytest.raises(broker.ArtifactBrokerError) as raised:
        broker.presign_with_broker(
            config,
            operation="put",
            project="yoke",
            subject=42,
            run_id=5,
            filename="shot.png",
        )
    assert raised.value.code == "artifact_broker_response_invalid"


def test_broker_named_refusal_keeps_recovery_without_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _broker_env(monkeypatch, tmp_path)
    config = broker.broker_config()
    assert config is not None
    body = json.dumps(
        {
            "error": {
                "code": "authorization_invalid",
                "message": "the token matches no hosted tenant",
                "recovery": "restart this tenant runtime",
            }
        }
    ).encode("utf-8")

    def refuse(*_args, **_kwargs):
        raise urllib.error.HTTPError(config.url, 401, "Unauthorized", {}, io.BytesIO(body))

    monkeypatch.setattr(broker.urllib.request, "urlopen", refuse)
    with pytest.raises(broker.ArtifactBrokerError) as raised:
        broker.presign_with_broker(
            config, operation="get", project="yoke", subject=42,
            run_id=5, filename="shot.png",
        )
    assert raised.value.code == "artifact_broker_authorization_invalid"
    assert "restart this tenant runtime" in str(raised.value)
    assert "tenant-service-token" not in str(raised.value)


def test_handlers_use_broker_for_presign_store_and_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _broker_env(monkeypatch, tmp_path)
    operations = []

    def sign(_config, *, operation, run_id, filename, **_kwargs):
        operations.append(operation)
        return _signed(operation, run_id, filename)

    with test_database() as conn:
        run_id = _seed_run(conn)
        with (
            patch.object(broker, "presign_with_broker", side_effect=sign),
            patch("yoke_core.domain.qa_artifact_storage._upload_bytes") as upload,
        ):
            presigned = handle_qa_artifact_presign(
                _request(
                    "qa.artifact.presign",
                    10,
                    {"run_id": run_id, "filename": "browser.png"},
                )
            )
            added = handle_qa_artifact_add(
                _request(
                    "qa.artifact.add",
                    10,
                    {
                        "run_id": run_id,
                        "artifact_type": "log",
                        "content_base64": base64.b64encode(b"evidence").decode(),
                        "filename": "evidence.log",
                    },
                )
            )
            assert added.primary_success, added.error
            artifact_id = int(added.result_payload["qa_artifact_id"])
            row = conn.execute(
                "SELECT artifact_handle FROM qa_artifacts WHERE id=%s",
                (artifact_id,),
            ).fetchone()
            read = handle_qa_artifact_read(artifact_read_request(10, artifact_id))

    assert presigned.primary_success, presigned.error
    assert json.loads(row[0])["backend"] == "s3"
    upload.assert_called_once()
    assert read.primary_success, read.error
    assert read.result_payload["download_url"] == "https://s3.example/get"
    assert operations == ["put", "put", "get"]
