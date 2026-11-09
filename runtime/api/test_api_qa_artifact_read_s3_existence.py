"""An S3 evidence read reports ``ready`` only while the object exists."""

from __future__ import annotations

import io
import urllib.error
from unittest.mock import patch

import pytest

from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.qa_artifact_read_test_support import (
    CREDS,
    artifact_read_request,
    seed_artifact,
    seed_s3_configuration,
)
from yoke_core.domain.handlers.qa_artifact_read import (
    EVIDENCE_MISSING,
    handle_qa_artifact_read,
)
from yoke_core.domain.signed_object_transfer import (
    ObjectTransferError,
    probe_signed_object,
)

BUCKET = "yoke-prod-artifacts"
KEY = "qa-artifacts/yoke/42/1/output.png"
CREDENTIALS = "yoke_core.domain.qa_artifact_configuration._capability_credentials"
URLOPEN = "yoke_core.domain.signed_object_transfer.urllib.request.urlopen"


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://s3", code, "status", {}, io.BytesIO())


def _read_with_store_answer(answer):
    with test_database() as conn:
        artifact_id = seed_artifact(
            conn, handle={"backend": "s3", "bucket": BUCKET, "key": KEY}
        )
        seed_s3_configuration(conn, bucket=BUCKET)
        with (
            patch(CREDENTIALS, return_value=CREDS),
            patch(URLOPEN, side_effect=answer) as urlopen,
        ):
            outcome = handle_qa_artifact_read(artifact_read_request(10, artifact_id))
    return outcome, urlopen


def test_present_object_is_ready_after_a_one_byte_probe() -> None:
    outcome, urlopen = _read_with_store_answer(lambda *a, **k: io.BytesIO(b"x"))

    assert outcome.primary_success
    assert outcome.result_payload["disposition"] == "ready"
    probe = urlopen.call_args_list[0].args[0]
    assert probe.full_url == outcome.result_payload["download_url"]
    assert probe.get_header("Range") == "bytes=0-0"


@pytest.mark.parametrize("status", [403, 404])
def test_missing_object_reports_evidence_missing_with_recovery(status) -> None:
    outcome, _ = _read_with_store_answer(_http_error(status))

    assert outcome.primary_success
    result = outcome.result_payload
    assert result["disposition"] == EVIDENCE_MISSING == "evidence_missing"
    assert "download_url" not in result
    assert f"s3://{BUCKET}/{KEY}" in result["detail"]
    assert "Re-run the QA case" in result["detail"]


def test_unreachable_store_refuses_by_name() -> None:
    outcome, _ = _read_with_store_answer(_http_error(500))

    assert not outcome.primary_success
    assert outcome.error.code == "s3_download_failed"


def test_zero_byte_object_still_exists() -> None:
    with patch(URLOPEN, side_effect=_http_error(416)):
        probe_signed_object("https://s3/x", bucket=BUCKET, key=KEY)


def test_network_failure_is_a_download_failure() -> None:
    with patch(URLOPEN, side_effect=urllib.error.URLError("refused")):
        with pytest.raises(ObjectTransferError) as raised:
            probe_signed_object("https://s3/x", bucket=BUCKET, key=KEY)
    assert raised.value.code == "s3_download_failed"
