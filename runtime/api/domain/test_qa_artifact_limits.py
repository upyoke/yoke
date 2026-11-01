"""New evidence obeys the upload limit, including direct S3 submissions."""

import io
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from runtime.api.domain.test_qa_artifact_broker import (
    _broker_env, _request, _seed_run, _signed,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.qa_artifact_limits import MAX_ARTIFACT_BYTES
from yoke_core.domain import qa_artifact_broker as broker
from yoke_core.domain import qa_artifact_size, qa_artifact_storage as storage
from yoke_core.domain.browser_qa_upload import _upload_artifact
from yoke_core.domain.browser_qa_steps import QaArtifactWriteError
from yoke_core.domain.handlers.qa_artifact_add import handle_qa_artifact_add
from yoke_core.domain.signed_object_transfer import ObjectTransferError, signed_object_size


@pytest.mark.parametrize("submission", ["bytes", "file", "browser"])
def test_oversized_new_content_is_refused_before_upload(tmp_path, submission):
    content = b"x" * (MAX_ARTIFACT_BYTES + 1)
    source = tmp_path / "large.png"
    source.write_bytes(content)
    with patch("urllib.request.urlopen") as upload:
        if submission == "browser":
            with pytest.raises(QaArtifactWriteError, match="artifact_too_large"):
                _upload_artifact("https://s3.example/put", str(source), "image/png")
        else:
            with patch.object(storage, "requirement_storage_owner", return_value={}):
                with pytest.raises(ValueError, match="limit is"):
                    if submission == "bytes":
                        storage.store_artifact_bytes(
                            None, requirement_id=1, run_id=1,
                            filename="large.png", content=content,
                        )
                    else:
                        storage.store_artifact_file(
                            None, requirement_id=1, run_id=1, path=source,
                        )
        upload.assert_not_called()


@pytest.mark.parametrize("size", [MAX_ARTIFACT_BYTES, MAX_ARTIFACT_BYTES + 1])
def test_hosted_handle_registration_checks_object_size(tmp_path, monkeypatch, size):
    _broker_env(monkeypatch, tmp_path)
    with test_database() as conn:
        run = _seed_run(conn)
        signed = _signed("get", run, "large.png")
        with (
            patch.object(broker, "presign_with_broker", return_value=signed),
            patch.object(qa_artifact_size, "presign_with_broker", return_value=signed),
            patch.object(qa_artifact_size, "signed_object_size", return_value=size) as measure,
        ):
            result = handle_qa_artifact_add(_request("qa.artifact.add", 10, {
                "run_id": run, "artifact_type": "screenshot",
                "artifact_handle": {"backend": "s3", "bucket": signed.bucket, "key": signed.key},
            }))
        measure.assert_called_once_with(signed.url, bucket=signed.bucket, key=signed.key)
        if size > MAX_ARTIFACT_BYTES:
            assert not result.primary_success
            assert result.error.code == "artifact_too_large"
            assert "smaller region" in result.error.message
        else:
            assert result.primary_success, result.error
        count = conn.execute("SELECT count(*) FROM qa_artifacts").fetchone()[0]
        assert count == int(size <= MAX_ARTIFACT_BYTES)


def test_handle_size_failure_is_a_named_refusal(tmp_path, monkeypatch):
    _broker_env(monkeypatch, tmp_path)
    with test_database() as conn:
        run = _seed_run(conn)
        signed = _signed("get", run, "shot.png")
        with patch.object(qa_artifact_size, "handle_size", side_effect=OSError("private")):
            result = handle_qa_artifact_add(_request("qa.artifact.add", 10, {
                "run_id": run, "artifact_type": "screenshot",
                "artifact_handle": {"backend": "s3", "bucket": signed.bucket, "key": signed.key},
            }))
        assert not result.primary_success
        assert result.error.code == "artifact_size_unavailable"
        assert "repair artifact store access" in result.error.message
        assert "private" not in result.error.message


def test_machine_store_size_uses_head_object(monkeypatch):
    monkeypatch.setattr(qa_artifact_size, "broker_config", lambda: None)
    from yoke_core.domain import universe_artifact_store
    from yoke_core.domain.handlers import qa_artifact_presign

    monkeypatch.setattr(qa_artifact_presign, "_aws_region", lambda *_: "us-east-1")
    with patch.object(universe_artifact_store, "_client") as client:
        client.return_value.head_object.return_value = {"ContentLength": MAX_ARTIFACT_BYTES + 1}
        size = qa_artifact_size.handle_size(
            None, {"project": "example", "project_id": 1}, 1,
            {"backend": "s3", "bucket": "evidence", "key": "object"},
        )
    assert size == MAX_ARTIFACT_BYTES + 1
    client.return_value.head_object.assert_called_once_with(Bucket="evidence", Key="object")


@pytest.mark.parametrize("status,headers,expected", [
    (206, {"Content-Range": "bytes 0-0/41319003"}, 41319003),
    (200, {"Content-Length": "30000000"}, 30000000),
])
def test_signed_size_reads_headers_without_downloading(status, headers, expected):
    response = MagicMock()
    response.__enter__.return_value = response
    response.status, response.headers = status, headers
    with patch("urllib.request.urlopen", return_value=response) as open_url:
        assert signed_object_size("https://s3.example/get", bucket="b", key="k") == expected
        response.read.assert_not_called()
    assert open_url.call_args.args[0].get_header("Range") == "bytes=0-0"


def test_signed_size_refuses_unknown_size():
    response = io.BytesIO()
    response.status, response.headers = 206, {"Content-Range": "bytes 0-0/*"}
    with patch("urllib.request.urlopen", return_value=response):
        with pytest.raises(ObjectTransferError, match="cannot measure"):
            signed_object_size("https://s3.example/get", bucket="b", key="k")


def test_signed_size_accepts_empty_object():
    error = urllib.error.HTTPError(
        "https://s3.example/get", 416, "range", {"Content-Range": "bytes */0"}, None,
    )
    with patch("urllib.request.urlopen", side_effect=error):
        assert signed_object_size("https://s3.example/get", bucket="b", key="k") == 0
