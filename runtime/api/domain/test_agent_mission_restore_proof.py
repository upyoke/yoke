"""Mission cleanup proof reads owned local/S3 bytes and the shared baseline contract."""

import base64
import json

import pytest

from yoke_core.domain.agent_mission_restore import recorded_mission_restore
from yoke_core.domain.qa_plan_execution_abort_state import starting_state_restore_proven


@pytest.mark.parametrize("receipt,expected", [
    ({"restored": True, "baseline": "clean"}, True),
    ({"restored": False, "baseline": "clean"}, False),
    ({"restored": True, "baseline": "other"}, False),
    ({"restored": 1, "baseline": "clean"}, False),
    ({"restored": "true", "baseline": "clean"}, False),
    ({}, False),
    (None, False),
])
def test_baseline_proof_requires_true_and_the_declared_baseline(receipt, expected):
    assert starting_state_restore_proven(
        {"host_baseline": "clean", "starting_state": "baseline"}, receipt
    ) is expected


def test_as_is_keeps_the_no_restore_receipt_contract():
    assert starting_state_restore_proven(
        {"starting_state": "as_is"},
        {"restored": False, "reason": "no declared starting state"},
    )


@pytest.mark.parametrize("payload", [
    {"restored": True, "baseline": "clean"},
    {"restored": False, "baseline": "clean"},
    {"restored": True, "baseline": "other"},
    "not an object",
])
def test_s3_restore_reads_authorized_payload_without_trusting_metadata(monkeypatch, payload):
    from yoke_core.domain import agent_mission_restore, qa_artifact_owner, qa_artifact_text_inline
    from yoke_core.domain.handlers import qa_artifact_read

    handle = {"backend": "s3", "bucket": "test-store", "key": "receipt.json"}
    artifact = {"artifact_handle": json.dumps(handle), "metadata": {"restored": True}}
    monkeypatch.setattr(agent_mission_restore, "query_one", lambda *_: artifact)
    monkeypatch.setattr(qa_artifact_owner, "requirement_storage_owner", lambda *_: {"project_id": 1})
    reads = []

    def read(conn, row, stored):
        reads.append((row["run_id"], stored))
        return {"download_url": "https://artifacts.invalid/owned-receipt"}, None

    monkeypatch.setattr(qa_artifact_read, "_s3_result", read)
    monkeypatch.setattr(
        qa_artifact_text_inline, "inline_text_base64",
        lambda _: base64.b64encode(json.dumps(payload).encode()).decode(),
    )
    actual = recorded_mission_restore(object(), requirement_id=4, run_id=9)
    assert actual == (payload if isinstance(payload, dict) else None)
    assert reads == [(9, handle)]


@pytest.mark.parametrize("content", [None, "not-base64", base64.b64encode(b"bad JSON").decode()])
def test_unreadable_or_malformed_restore_does_not_prove_cleanup(monkeypatch, content):
    from yoke_core.domain import agent_mission_restore, qa_artifact_owner
    from yoke_core.domain.handlers import qa_artifact_read

    monkeypatch.setattr(agent_mission_restore, "query_one", lambda *_: {
        "artifact_handle": json.dumps({"backend": "local", "path": "/receipt.json"}),
        "metadata": None,
    })
    monkeypatch.setattr(qa_artifact_owner, "requirement_storage_owner", lambda *_: {})
    monkeypatch.setattr(qa_artifact_read, "_local_result", lambda *_: {"content_base64": content})
    assert recorded_mission_restore(object(), requirement_id=4, run_id=9) is None
