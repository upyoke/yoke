"""Question attachments use QA storage, authorized reads and portable refs."""

from __future__ import annotations

import base64
import json
from contextlib import contextmanager

import pytest

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    _project,
    seed_session,
)
from runtime.api.domain.coordination_claim_test_support import PROJECT_YOKE
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.operator_question_attachments import upload_files, validate_uploads
from yoke_contracts.qa_artifact_limits import MAX_ARTIFACT_BYTES
from yoke_core.domain.decision_request_question_filing import (
    file_question,
    list_questions,
)
from yoke_core.domain.decision_requests import RoleAuthority
from yoke_core.domain.handlers.decision_request_question_attachments import handle_read


@pytest.mark.parametrize("kind", ["missing", "unsupported", "oversize"])
def test_invalid_file_refuses_before_upload(tmp_path, kind):
    path = tmp_path / ("note.txt" if kind == "unsupported" else "image.png")
    if kind == "unsupported":
        path.write_text("plain text")
    elif kind == "oversize":
        with path.open("wb") as stream:
            stream.truncate(MAX_ARTIFACT_BYTES + 1)
    with pytest.raises(ValueError, match="operator_question_attachment_") as exc:
        upload_files([path])
    assert "retry ask --attach PATH" in str(exc.value)


def test_server_rejects_invalid_type_or_bytes():
    for raw in [
        {"filename": "bad.txt", "content_type": "text/plain", "content_base64": "YQ=="},
        {"filename": "bad.png", "content_type": "image/png", "content_base64": "!"},
    ]:
        with pytest.raises(ValueError, match="operator_question_attachment_"):
            validate_uploads([raw])


def test_two_attachments_share_qa_storage_and_keep_names_on_reads(
    test_db, tmp_path, monkeypatch
):
    _project(test_db)
    session = "question-attachments-worker"
    seed_session(test_db, session)
    from yoke_core.domain.qa_artifact_handle import local_handle

    calls = []

    def store(conn, **kwargs):
        calls.append(kwargs)
        path = tmp_path / kwargs["filename"]
        path.write_bytes(kwargs["content"])
        return local_handle(str(path), kwargs["content_type"])

    monkeypatch.setattr(
        "yoke_core.domain.decision_request_question_attachments.store_owned_artifact_bytes",
        store,
    )
    uploads = [
        {
            "filename": name,
            "content_type": content_type,
            "content_base64": base64.b64encode(content).decode(),
        }
        for name, content_type, content in [
            ("header.png", "image/png", b"image bytes"),
            ("brief.pdf", "application/pdf", b"%PDF brief"),
        ]
    ]
    row, created = file_question(
        test_db,
        kind="operator_question",
        subject_type="session_question",
        subject_key=f"{session}:choose",
        requesting_session_id=session,
        session_id=session,
        originator_actor_id=1,
        project_id=PROJECT_YOKE,
        role_authorities=[RoleAuthority("project", PROJECT_YOKE, "owner")],
        subject_context={"question": "Which header?"},
        attachments=uploads,
    )
    assert created and row["attachment_count"] == 2
    assert row["attachment_names"] == ["header.png", "brief.pdf"]
    assert all(
        call["owner"]["artifact_subject"] == f"decision-request-{row['id']}"
        for call in calls
    )
    assert (
        list_questions(test_db, session)[0]["attachment_names"]
        == row["attachment_names"]
    )
    again, created = file_question(
        test_db,
        kind="operator_question",
        subject_type="session_question",
        subject_key=f"{session}:choose",
        requesting_session_id=session,
        session_id=session,
        originator_actor_id=1,
        project_id=PROJECT_YOKE,
        role_authorities=[RoleAuthority("project", PROJECT_YOKE, "owner")],
        subject_context={"question": "Which header?"},
        attachments=uploads,
    )
    assert not created and again["id"] == row["id"] and len(calls) == 2

    @contextmanager
    def connection():
        yield test_db

    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", connection)
    # The shared reader resolves its path guard from qa_artifacts at the call site.
    monkeypatch.setattr(
        "yoke_core.domain.qa_artifacts.is_server_evidence_path", lambda *a, **k: True
    )
    request = FunctionCallRequest(
        function="decision_requests.attachment.read",
        target=TargetRef(kind="global"),
        actor=ActorContext(actor_id="1", session_id=session),
        payload={"request_id": row["id"], "artifact_id": 1},
    )
    read = handle_read(request)
    assert read.primary_success, read.error
    denied = handle_read(
        request.model_copy(
            update={"actor": ActorContext(actor_id="999", session_id="other")}
        )
    )
    assert not denied.primary_success and denied.error.code == "permission_denied"
    assert base64.b64decode(read.result_payload["content_base64"]) == b"image bytes"
    from yoke_core.domain.decision_request_attachment_archive import (
        question_sources,
        question_entry,
    )

    sources = question_sources(test_db)
    assert len(sources) == 2
    replacement = local_handle(str(tmp_path / "restored.png"), "image/png")
    question_entry(test_db, sources[0], replacement)
    context = json.loads(
        test_db.execute(
            "SELECT subject_context FROM decision_requests WHERE id=%s", (row["id"],)
        ).fetchone()[0]
    )
    assert context["artifacts"][0]["artifact_handle"] == replacement


def test_storage_refusal_keeps_original_question_pending(test_db, monkeypatch):
    from yoke_core.domain.handlers.decision_request_questions import handle_ask
    from yoke_core.domain.qa_artifact_storage import ArtifactStorageError
    from yoke_core.domain.decision_request_rows import request_row
    from unittest.mock import Mock

    _project(test_db)
    session = "question-storage-worker"
    seed_session(test_db, session)
    old, _ = file_question(
        test_db,
        kind="operator_question",
        subject_type="session_question",
        subject_key=f"{session}:choose",
        requesting_session_id=session,
        session_id=session,
        originator_actor_id=1,
        project_id=PROJECT_YOKE,
        role_authorities=[RoleAuthority("project", PROJECT_YOKE, "owner")],
        subject_context={"question": "Which header?"},
    )

    @contextmanager
    def connection():
        yield test_db

    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", connection)
    monkeypatch.setattr(
        "yoke_core.domain.decision_request_question_attachments.store_owned_artifact_bytes",
        Mock(
            side_effect=ArtifactStorageError(
                "store_unavailable", "Storage refused the upload"
            )
        ),
    )
    outcome = handle_ask(
        FunctionCallRequest(
            function="decision_requests.ask",
            target=TargetRef(kind="global"),
            actor=ActorContext(actor_id="1", session_id=session),
            payload={
                "key": "choose",
                "question": "Which new header?",
                "replaces": old["id"],
                "attachments": [
                    {
                        "filename": "header.png",
                        "content_type": "image/png",
                        "content_base64": "aW1hZ2U=",
                    }
                ],
            },
        )
    )
    assert not outcome.primary_success
    assert outcome.error.code == "operator_question_attachment_store_failed"
    assert "repair the QA evidence store" in outcome.error.message
    assert request_row(test_db, old["id"])["status"] == "pending"
    assert len(list_questions(test_db, session)) == 1
