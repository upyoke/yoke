"""Moving capture-machine evidence into the serving store, in place."""

from __future__ import annotations

import base64
import hashlib
import json
from unittest.mock import patch

import pytest

from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.qa_artifact_read_test_support import (
    artifact_read_request,
    seed_artifact,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import qa_evidence_portability
from yoke_core.domain.handlers.qa_artifact_read import handle_qa_artifact_read
from yoke_core.domain.handlers.qa_artifact_rehome import handle_qa_artifact_rehome
from yoke_core.domain.qa_artifact_storage import (
    ArtifactStorageError,
    store_artifact_bytes,
)

BYTES = b"\x89PNG screenshot bytes"
STORED = {
    "backend": "s3",
    "bucket": "tenant-artifacts",
    "key": "tenant/qa-artifacts/yoke/42/1/shot.png",
    "content_type": "image/png",
}


def _request(requirement_id: int, artifact_id: int) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="qa.artifact.rehome",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
        payload={
            "artifact_id": artifact_id,
            "content_base64": base64.b64encode(BYTES).decode("ascii"),
        },
    )


def _artifact_rows(conn, artifact_id: int) -> list[dict]:
    run_id = conn.execute(
        "SELECT qa_run_id FROM qa_artifacts WHERE id=%s", (artifact_id,)
    ).fetchone()[0]
    return [
        dict(row)
        for row in conn.execute(
            "SELECT id, artifact_handle, metadata FROM qa_artifacts "
            "WHERE qa_run_id=%s ORDER BY id",
            (run_id,),
        ).fetchall()
    ]


def test_local_capture_is_stored_and_its_handle_swapped_in_place(tmp_path) -> None:
    local = {"backend": "local", "path": "/Users/capture/shot.png"}
    stored_calls: list[dict] = []

    def store(conn, **kwargs):
        stored_calls.append(kwargs)
        return STORED

    with test_database() as conn:
        artifact_id = seed_artifact(conn, handle=local, metadata={"label": "home"})
        with patch(
            "yoke_core.domain.qa_artifact_storage.store_artifact_bytes", store
        ):
            outcome = handle_qa_artifact_rehome(_request(10, artifact_id))
        rows = _artifact_rows(conn, artifact_id)

    assert outcome.primary_success, outcome
    assert outcome.result_payload["rehomed"] is True
    assert outcome.result_payload["previous_handle"] == local
    assert stored_calls[0]["filename"] == "shot.png"
    assert stored_calls[0]["content"] == BYTES
    # One artifact, same id: no second gallery beside the first.
    assert [row["id"] for row in rows] == [artifact_id]
    assert json.loads(rows[0]["artifact_handle"]) == STORED
    metadata = json.loads(rows[0]["metadata"])
    assert metadata["label"] == "home"
    assert metadata["rehomed_from"]["artifact_handle"] == local
    assert (
        metadata["rehomed_from"]["sha256"] == hashlib.sha256(BYTES).hexdigest()
    )


def test_object_store_artifact_is_left_alone() -> None:
    with test_database() as conn:
        artifact_id = seed_artifact(conn, handle=STORED)
        with patch(
            "yoke_core.domain.qa_artifact_storage.store_artifact_bytes",
            side_effect=AssertionError("must not store again"),
        ):
            outcome = handle_qa_artifact_rehome(_request(10, artifact_id))

    assert outcome.primary_success
    assert outcome.result_payload["rehomed"] is False
    assert outcome.result_payload["artifact_handle"] == STORED


def test_artifact_of_another_requirement_is_refused() -> None:
    with test_database() as conn:
        artifact_id = seed_artifact(
            conn, handle={"backend": "local", "path": "/tmp/x.png"}
        )
        outcome = handle_qa_artifact_rehome(_request(11, artifact_id))

    assert not outcome.primary_success
    assert outcome.error is not None
    assert outcome.error.code == "target_invalid"


def test_storage_refusal_reaches_the_caller_by_name() -> None:
    def refuse(conn, **_kwargs):
        raise ArtifactStorageError("evidence_not_portable", "no hosted store here")

    with test_database() as conn:
        artifact_id = seed_artifact(
            conn, handle={"backend": "local", "path": "/tmp/x.png"}
        )
        with patch(
            "yoke_core.domain.qa_artifact_storage.store_artifact_bytes", refuse
        ):
            outcome = handle_qa_artifact_rehome(_request(10, artifact_id))
        handle = conn.execute(
            "SELECT artifact_handle FROM qa_artifacts WHERE id=%s", (artifact_id,)
        ).fetchone()[0]

    assert outcome.error is not None
    assert outcome.error.code == "evidence_not_portable"
    assert json.loads(handle)["backend"] == "local"


def test_unservable_local_read_names_where_it_was_recorded(tmp_path) -> None:
    recorded = str(tmp_path / "elsewhere" / "shot.png")
    with test_database() as conn:
        artifact_id = seed_artifact(
            conn,
            handle={"backend": "local", "path": recorded},
            metadata={"machine": "Capture Mac"},
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

    assert outcome.result_payload["disposition"] == "evidence_on_machine"
    assert outcome.result_payload["recorded_path"] == recorded


def test_local_write_through_a_database_door_refuses(monkeypatch) -> None:
    monkeypatch.setattr(
        qa_evidence_portability, "administered_elsewhere_env", lambda: "prod-db-admin"
    )
    with test_database() as conn:
        seed_artifact(conn, handle={"backend": "local", "path": "/tmp/x.png"})
        run_id = conn.execute(
            "SELECT id FROM qa_runs WHERE qa_requirement_id=10"
        ).fetchone()[0]
        with pytest.raises(ArtifactStorageError) as raised:
            store_artifact_bytes(
                conn,
                requirement_id=10,
                run_id=int(run_id),
                filename="shot.png",
                content=BYTES,
                content_type="image/png",
            )

    assert raised.value.code == "evidence_not_portable"
    assert "--env prod" in str(raised.value)
