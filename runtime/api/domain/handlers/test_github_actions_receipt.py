"""Artifact reads are bound, digest verified and bounded before JSON use."""

import hashlib
import io
import json
import zipfile

import pytest

from runtime.api.fixtures.hosted_promotion import payload
from yoke_core.domain import github_actions_receipt as receipts
from yoke_core.domain.handlers import github_actions_run


def archive(value):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        zipped.writestr("promotion-receipt.json", json.dumps(value))
    return output.getvalue()


@pytest.fixture
def receipt_source(monkeypatch):
    value = payload()
    raw = archive(value)
    artifact = {
        "id": 456,
        "name": "promotion-receipt-123-1",
        "expired": False,
        "size_in_bytes": len(raw),
        "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "workflow_run": {"id": 123},
    }
    monkeypatch.setattr(
        receipts,
        "rest_get",
        lambda *a, **k: {"total_count": 1, "artifacts": [artifact]},
    )
    monkeypatch.setattr(receipts, "_fetch_with_retry", lambda *a, **k: raw)
    run = {
        "id": 123,
        "run_attempt": 1,
        "head_sha": "e" * 40,
        "path": ".github/workflows/yoke-release-promote.yml@main",
        "display_title": "promotion",
    }
    return artifact, run, raw


def test_exact_run_attempt_artifact_digest_and_payload(receipt_source):
    artifact, run, _ = receipt_source
    result = receipts.read_run_receipt(
        "upyoke/platform", run, "promotion-receipt", token="secret"
    )
    assert result["workflow_path"] == ".github/workflows/yoke-release-promote.yml"
    assert result["artifact_id"] == artifact["id"]
    assert result["payload"] == payload()


@pytest.mark.parametrize(
    "key,value,reason",
    [
        ("name", "promotion-receipt-123-2", "workflow_receipt_missing"),
        ("expired", True, "workflow_receipt_artifact_invalid"),
        (
            "size_in_bytes",
            receipts.RECEIPT_LIMIT_BYTES + 1,
            "workflow_receipt_artifact_invalid",
        ),
        ("workflow_run", {"id": 999}, "workflow_receipt_artifact_invalid"),
        ("digest", "sha256:" + "0" * 64, "workflow_receipt_digest_mismatch"),
    ],
)
def test_unattributable_or_corrupt_artifact_refuses(receipt_source, key, value, reason):
    artifact, run, _ = receipt_source
    artifact[key] = value
    with pytest.raises(receipts.ActionsReceiptRefused) as error:
        receipts.read_run_receipt(
            "upyoke/platform", run, "promotion-receipt", token="secret"
        )
    assert error.value.reason == reason


def test_failed_run_never_reads_receipt(monkeypatch):
    from runtime.api.domain.handlers.test_github_actions_run import (
        _make_request,
        _RESOLVED,
    )

    monkeypatch.setattr(
        github_actions_run,
        "_validate_and_resolve",
        lambda *a, **k: (
            github_actions_run.RunGetRequest(
                repo="upyoke/yoke",
                run_id="123",
                project="yoke",
                receipt_artifact_prefix="promotion-receipt",
            ),
            _RESOLVED.token,
            None,
        ),
    )
    monkeypatch.setattr(
        "yoke_core.domain.github_actions_rest.rest_get",
        lambda *a, **k: {"id": 123, "status": "completed", "conclusion": "failure"},
    )
    monkeypatch.setattr(
        github_actions_run, "with_effective_conclusion", lambda r, d, **k: d
    )
    monkeypatch.setattr(
        receipts,
        "read_run_receipt",
        lambda *a, **k: pytest.fail("failed promotion read receipt"),
    )
    result = github_actions_run.handle_run_get(_make_request())
    assert result.result_payload["state"] == "failed"
    assert result.result_payload["receipt"] is None
