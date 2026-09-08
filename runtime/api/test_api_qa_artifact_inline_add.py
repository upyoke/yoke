"""Inline ``content_base64`` path for ``qa.artifact.add``."""

from __future__ import annotations

import base64
import io
import json
import shutil
import struct
import urllib.error
import zlib
from unittest.mock import patch

from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.qa_artifact_read_test_support import artifact_read_request
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import machine_config, project_scratch_dir
from yoke_core.domain.handlers.qa_artifact_add import handle_qa_artifact_add
from yoke_core.domain.handlers.qa_artifact_read import (
    MAX_INLINE_BYTES,
    handle_qa_artifact_read,
)
from yoke_core.domain.handlers.qa_browser_writes import handle_qa_run_add
from yoke_core.domain.qa_artifact_handle import parse_handle
from yoke_core.domain.s3_presign import AwsCredentials


def _png_1x1() -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = zlib.compress(b"\x00\xff\x00\x00")
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", raw)
        + chunk(b"IEND", b"")
    )


class _UploadResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _request(payload) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="qa.artifact.add",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="qa_requirement", qa_requirement_id=10),
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
        run_outcome = handle_qa_run_add(
            FunctionCallRequest(
                function="qa.run.add",
                actor=ActorContext(actor_id="op", session_id="s-1"),
                target=TargetRef(kind="qa_requirement", qa_requirement_id=10),
                payload={"performed_by": "browser_substrate"},
            ),
        )
    assert run_outcome.primary_success, run_outcome.error
    return int(run_outcome.result_payload["qa_run_id"])


def test_handle_and_inline_content_are_mutually_exclusive() -> None:
    with test_database() as conn:
        run_id = _seed_run(conn)
        outcome = handle_qa_artifact_add(
            _request(
                {
                    "run_id": run_id,
                    "artifact_type": "screenshot",
                    "artifact_handle": {
                        "backend": "local",
                        "path": "/tmp/home.png",
                    },
                    "content_base64": base64.b64encode(b"x").decode("ascii"),
                    "filename": "home.png",
                }
            ),
        )
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert "not both" in outcome.error.message


def test_malformed_base64_preserves_the_diagnosed_error() -> None:
    with test_database() as conn:
        run_id = _seed_run(conn)
        outcome = handle_qa_artifact_add(
            _request(
                {
                    "run_id": run_id,
                    "artifact_type": "screenshot",
                    "content_base64": "@@@not-base64@@@",
                    "filename": "home.png",
                }
            ),
        )
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert "not valid base64" in outcome.error.message


def test_oversize_inline_content_names_the_reader_limit() -> None:
    with test_database() as conn:
        run_id = _seed_run(conn)
        with patch(
            "yoke_core.domain.qa_artifact_storage.MAX_ARTIFACT_BYTES",
            8,
        ):
            outcome = handle_qa_artifact_add(
                _request(
                    {
                        "run_id": run_id,
                        "artifact_type": "screenshot",
                        "content_base64": base64.b64encode(b"0123456789").decode(
                            "ascii"
                        ),
                        "filename": "home.png",
                    }
                ),
            )
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert "10 bytes" in outcome.error.message
    assert "limit is 8" in outcome.error.message
    assert MAX_INLINE_BYTES == 20 * 1024 * 1024


def test_configured_s3_receives_bytes_before_the_row_is_recorded() -> None:
    seen = {}

    def upload(request, timeout=None):
        seen["body"] = request.data
        seen["content_type"] = request.get_header("Content-type")
        return _UploadResponse()

    with test_database() as conn:
        run_id = _seed_run(conn)
        with (
            patch(
                "yoke_core.domain.handlers.qa_artifact_presign."
                "resolve_artifacts_bucket",
                return_value=("prod", "project-artifacts", None),
            ),
            patch(
                "yoke_core.domain.handlers.qa_artifact_presign._aws_region",
                return_value="us-east-1",
            ),
            patch(
                "yoke_core.domain.handlers.qa_artifact_presign."
                "_capability_credentials",
                return_value=AwsCredentials("access", "secret"),
            ),
            patch(
                "yoke_core.domain.s3_presign.presign_s3_url",
                return_value="https://project-artifacts.s3.amazonaws.com/key",
            ),
            patch("urllib.request.urlopen", side_effect=upload),
        ):
            outcome = handle_qa_artifact_add(
                _request(
                    {
                        "run_id": run_id,
                        "artifact_type": "screenshot",
                        "content_type": "image/png",
                        "content_base64": base64.b64encode(b"PNG").decode(),
                        "filename": "home.png",
                    }
                )
            )
        assert outcome.primary_success, outcome.error
        row = conn.execute(
            "SELECT artifact_handle FROM qa_artifacts WHERE id = %s",
            (outcome.result_payload["qa_artifact_id"],),
        ).fetchone()
    handle = json.loads(row[0])
    assert handle["backend"] == "s3"
    assert handle["bucket"] == "project-artifacts"
    assert seen == {"body": b"PNG", "content_type": "image/png"}


def test_configured_s3_upload_failure_has_no_local_fallback() -> None:
    with test_database() as conn:
        run_id = _seed_run(conn)
        with (
            patch(
                "yoke_core.domain.handlers.qa_artifact_presign."
                "resolve_artifacts_bucket",
                return_value=("prod", "project-artifacts", None),
            ),
            patch(
                "yoke_core.domain.handlers.qa_artifact_presign._aws_region",
                return_value="us-east-1",
            ),
            patch(
                "yoke_core.domain.handlers.qa_artifact_presign."
                "_capability_credentials",
                return_value=AwsCredentials("access", "secret"),
            ),
            patch(
                "yoke_core.domain.s3_presign.presign_s3_url",
                return_value="https://project-artifacts.s3.amazonaws.com/key",
            ),
            patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.URLError("connection refused"),
            ),
        ):
            outcome = handle_qa_artifact_add(
                _request(
                    {
                        "run_id": run_id,
                        "artifact_type": "screenshot",
                        "content_base64": base64.b64encode(b"PNG").decode(),
                        "filename": "home.png",
                    }
                )
            )
        count = conn.execute("SELECT COUNT(*) FROM qa_artifacts").fetchone()[0]
    assert not outcome.primary_success
    assert outcome.error.code == "s3_upload_failed"
    assert "connection refused" in outcome.error.message
    assert count == 0


def test_unsafe_filename_is_payload_invalid() -> None:
    with test_database() as conn:
        run_id = _seed_run(conn)
        outcome = handle_qa_artifact_add(
            _request(
                {
                    "run_id": run_id,
                    "artifact_type": "screenshot",
                    "content_base64": base64.b64encode(b"x").decode("ascii"),
                    "filename": "../escape.png",
                }
            ),
        )
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert "unsafe artifact key segment" in outcome.error.message


def test_inline_png_round_trips_through_authorized_read(
    tmp_path,
    monkeypatch,
) -> None:
    png = _png_1x1()
    monkeypatch.setenv(project_scratch_dir.ENV_KEY, str(tmp_path / "scratch"))
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path / "machine-home"))
    monkeypatch.setenv("YOKE_SESSION_ID", "capture-session")
    monkeypatch.setenv("YOKE_RUN_ID", "capture-run")
    with test_database() as conn:
        run_id = _seed_run(conn)
        add_outcome = handle_qa_artifact_add(
            _request(
                {
                    "run_id": run_id,
                    "artifact_type": "screenshot",
                    "content_type": "image/png",
                    "content_base64": base64.b64encode(png).decode("ascii"),
                    "filename": "home.png",
                }
            ),
        )
        assert add_outcome.primary_success, add_outcome.error
        artifact_id = int(add_outcome.result_payload["qa_artifact_id"])
        row = conn.execute(
            "SELECT artifact_handle FROM qa_artifacts WHERE id = %s",
            (artifact_id,),
        ).fetchone()
        handle = parse_handle(row[0])
        assert handle["backend"] == "local"
        assert str(tmp_path / "machine-home" / "artifacts") in handle["path"]
        shutil.rmtree(tmp_path / "scratch", ignore_errors=True)
        read_outcome = handle_qa_artifact_read(artifact_read_request(10, artifact_id))
        wrong_owner = handle_qa_artifact_read(artifact_read_request(999, artifact_id))
    assert read_outcome.primary_success, read_outcome.error
    assert read_outcome.result_payload["disposition"] == "ready"
    assert base64.b64decode(read_outcome.result_payload["content_base64"]) == png
    assert not wrong_owner.primary_success
    assert wrong_owner.error.code == "target_invalid"


def test_existing_s3_handle_add_still_records_the_authorized_handle() -> None:
    with test_database() as conn:
        run_id = _seed_run(conn)
        with patch(
            "yoke_core.domain.handlers.qa_artifact_presign.resolve_artifacts_bucket",
            return_value=("prod", "p-prod-artifacts", None),
        ):
            outcome = handle_qa_artifact_add(
                _request(
                    {
                        "run_id": run_id,
                        "artifact_type": "screenshot",
                        "content_type": "image/png",
                        "artifact_handle": {
                            "backend": "s3",
                            "bucket": "p-prod-artifacts",
                            "key": "qa-artifacts/yoke/42/1/home.png",
                        },
                    }
                ),
            )
        assert outcome.primary_success, outcome.error
        row = conn.execute(
            "SELECT artifact_handle FROM qa_artifacts WHERE id = %s",
            (outcome.result_payload["qa_artifact_id"],),
        ).fetchone()
    assert json.loads(row[0])["backend"] == "s3"
