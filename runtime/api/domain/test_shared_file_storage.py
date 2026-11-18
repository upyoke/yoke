"""Shared files store by project path in S3 or on the serving machine's disk."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest

from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.qa_artifact_read_test_support import seed_s3_configuration
from runtime.api.shared_file_test_support import fake_object_store
from yoke_contracts.owner_private_path import is_owner_private_file
from yoke_contracts.shared_files import (
    SharedFilePathError,
    shared_file_content_type,
    shared_file_path,
    shared_file_url,
)
from yoke_core.domain import qa_artifact_broker as broker
from yoke_core.domain import shared_file_storage as storage

HTML = b"<!doctype html><title>plan</title><p>review me</p>"


@pytest.fixture(autouse=True)
def _serving_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "administered_elsewhere_env", lambda: "")
    for name in (
        broker.BUCKET_ENV,
        broker.PREFIX_ENV,
        broker.BROKER_URL_ENV,
        broker.TOKEN_FILE_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "/a.html",
        "a.html/",
        "a//b.html",
        "../a.html",
        "a/../b",
        ".env",
        "a b.html",
        "a%2Fb",
        "/".join(["d"] * 17),
    ],
)
def test_unsafe_paths_refuse_by_name(raw: str) -> None:
    with pytest.raises(SharedFilePathError) as raised:
        shared_file_path(raw)
    assert raised.value.code == "shared_file_path_invalid"


def test_paths_urls_and_content_types() -> None:
    assert shared_file_path(" plans/2026/review.html ") == "plans/2026/review.html"
    assert (
        shared_file_url("https://app.upyoke.com/api/orgs/acme/v1", "yoke", "plans/a.md")
        == "https://app.upyoke.com/api/orgs/acme/v1/files/yoke/plans/a.md"
    )
    assert shared_file_content_type("a.html") == "text/html; charset=utf-8"
    assert shared_file_content_type("a.md") == "text/markdown; charset=utf-8"
    assert shared_file_content_type("a.json") == "application/json; charset=utf-8"
    assert shared_file_content_type("a.png") == "image/png"
    assert shared_file_content_type("README") == "application/octet-stream"


def test_server_disk_round_trip_without_records() -> None:
    with test_database() as conn:
        before = conn.execute("SELECT COUNT(*) FROM qa_artifacts").fetchone()[0]
        stored = storage.put_shared_file(
            conn, project_id=1, project="yoke", path="plans/review.html", content=HTML
        )
        read = storage.read_shared_file(
            conn, project_id=1, project="yoke", path="plans/review.html"
        )
        after = conn.execute("SELECT COUNT(*) FROM qa_artifacts").fetchone()[0]
    target = storage.local_shared_file_root() / "yoke" / "plans" / "review.html"
    assert stored.backend == "local"
    assert stored.address == str(target)
    assert target.read_bytes() == HTML
    assert is_owner_private_file(target)
    assert read == HTML
    assert before == after


def test_missing_file_is_named() -> None:
    with test_database() as conn, pytest.raises(storage.SharedFileError) as raised:
        storage.read_shared_file(conn, project_id=1, project="yoke", path="nope.md")
    assert raised.value.code == "shared_file_not_found"


def test_database_door_refuses_local_write(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "administered_elsewhere_env", lambda: "prod-db-admin")
    with test_database() as conn, pytest.raises(storage.SharedFileError) as raised:
        storage.put_shared_file(
            conn, project_id=1, project="yoke", path="a.md", content=b"x"
        )
    assert raised.value.code == "shared_file_not_portable"
    assert "--env prod" in str(raised.value)


def test_configured_s3_round_trip_outlives_signed_link_expiry() -> None:
    with test_database() as conn, fake_object_store() as store:
        seed_s3_configuration(conn, bucket="yoke-prod-artifacts")
        stored = storage.put_shared_file(
            conn,
            project_id=1,
            project="yoke",
            path="data/report.json",
            content=b'{"ok":true}',
        )
        store.advance(10_000)  # every URL signed so far has expired
        read = storage.read_shared_file(
            conn, project_id=1, project="yoke", path="data/report.json"
        )
    assert stored.backend == "s3"
    assert (
        stored.address == "s3://yoke-prod-artifacts/shared-files/yoke/data/report.json"
    )
    assert store.objects["shared-files/yoke/data/report.json"] == (
        b'{"ok":true}',
        "application/json; charset=utf-8",
    )
    assert read == b'{"ok":true}'
    assert [method for method, _key in store.signed] == ["PUT", "GET"]
    assert not storage.local_shared_file_root().exists()


def test_failing_configured_store_never_falls_back_to_disk() -> None:
    with test_database() as conn, fake_object_store() as store:
        seed_s3_configuration(conn, bucket="yoke-prod-artifacts")
        store.fail_puts = True
        with pytest.raises(storage.SharedFileError) as raised:
            storage.put_shared_file(
                conn, project_id=1, project="yoke", path="a.html", content=HTML
            )
    assert raised.value.code == "s3_upload_failed"
    assert "s3://yoke-prod-artifacts/shared-files/yoke/a.html" in str(raised.value)
    assert not storage.local_shared_file_root().exists()


def _broker_config(tmp_path: Path) -> broker.ArtifactBrokerConfig:
    token = tmp_path / "broker.token"
    token.write_text("tenant-service-token\n", encoding="utf-8")
    return broker.ArtifactBrokerConfig(
        bucket="yoke-prod-artifacts",
        prefix="tenants/7",
        url="http://host.docker.internal:8601/tenant/qa-artifacts/presign",
        token_file=token,
    )


class _Reply(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        return None


def test_broker_signs_shared_file_by_tenant_prefix(tmp_path: Path, monkeypatch) -> None:
    config = _broker_config(tmp_path)
    sent = []

    def answer(request, timeout):
        sent.append(json.loads(request.data))
        return _Reply(
            json.dumps(
                {
                    "url": "https://s3.example/put",
                    "method": "PUT",
                    "bucket": "yoke-prod-artifacts",
                    "key": "tenants/7/shared-files/yoke/plans/a.html",
                    "expires_in": 900,
                }
            ).encode()
        )

    monkeypatch.setattr(broker.urllib.request, "urlopen", answer)
    signed = broker.presign_shared_file_with_broker(
        config, operation="put", project="yoke", path="plans/a.html"
    )
    assert signed.key == "tenants/7/shared-files/yoke/plans/a.html"
    assert sent == [
        {
            "operation": "put",
            "kind": "shared_file",
            "project": "yoke",
            "path": "plans/a.html",
        }
    ]


def test_broker_refuses_foreign_key_and_names_signer_refusal(
    tmp_path: Path, monkeypatch
) -> None:
    config = _broker_config(tmp_path)
    monkeypatch.setattr(
        broker.urllib.request,
        "urlopen",
        lambda *_a, **_k: _Reply(
            json.dumps(
                {
                    "url": "https://s3.example/get",
                    "method": "GET",
                    "bucket": "yoke-prod-artifacts",
                    "key": "tenants/8/shared-files/yoke/a.html",
                    "expires_in": 900,
                }
            ).encode()
        ),
    )
    with pytest.raises(broker.ArtifactBrokerError) as foreign:
        broker.presign_shared_file_with_broker(
            config, operation="get", project="yoke", path="a.html"
        )
    assert foreign.value.code == "artifact_broker_response_invalid"

    body = json.dumps(
        {
            "error": {
                "code": "request_invalid",
                "message": "kind unknown",
                "recovery": "upgrade the platform signer",
            }
        }
    ).encode()

    def refuse(*_a, **_k):
        raise urllib.error.HTTPError(
            config.url, 422, "Unprocessable", {}, io.BytesIO(body)
        )

    monkeypatch.setattr(broker.urllib.request, "urlopen", refuse)
    with pytest.raises(broker.ArtifactBrokerError) as refused:
        broker.presign_shared_file_with_broker(
            config, operation="get", project="yoke", path="a.html"
        )
    assert refused.value.code == "artifact_broker_request_invalid"
    assert "upgrade the platform signer" in str(refused.value)
