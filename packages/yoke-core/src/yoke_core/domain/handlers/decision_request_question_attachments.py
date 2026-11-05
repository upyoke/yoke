"""Authorized reads reuse the QA artifact reader and viewer transport."""

from __future__ import annotations

from pydantic import BaseModel
from yoke_contracts.api.function_call import HandlerOutcome
from yoke_core.domain.decision_request_question_attachments import owner
from yoke_core.domain.handlers.inbox_decisions import _actor_id, _error, _require_global


class QuestionAttachmentReadRequest(BaseModel):
    request_id: int
    artifact_id: int


def read_attachment(conn, request, artifact_id):
    from yoke_core.domain.handlers.qa_artifact_read import _local_result, _s3_result
    from yoke_core.domain.qa_artifact_handle import parse_handle

    artifact = next(
        (
            row
            for row in request["subject_context"].get("artifacts", [])
            if row["artifact_id"] == artifact_id
        ),
        None,
    )
    if artifact is None:
        raise LookupError(
            "operator_question_attachment_not_found: read get to see the question's attachment ids"
        )
    handle = parse_handle(artifact["artifact_handle"])
    row = {
        **owner(conn, request),
        "run_id": request["id"],
        "metadata": artifact["metadata"],
        "content_type": artifact["content_type"],
    }
    if handle["backend"] == "s3":
        result, error = _s3_result(conn, row, handle)
        if error is not None:
            return error
    else:
        result = _local_result(row, handle)
    return {
        "artifact_id": artifact_id,
        "backend": handle["backend"],
        "content_type": artifact["content_type"],
        **result,
    }


def handle_read(request):
    invalid = _require_global(request, request.function)
    if invalid is not None:
        return invalid
    actor_id = _actor_id(request, request.function)
    if isinstance(actor_id, HandlerOutcome):
        return actor_id
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.decision_request_rows import request_row
    from yoke_core.domain.decision_request_authority import authority_reason
    from yoke_core.domain.decision_request_question_filing import requester_can_read

    try:
        model = QuestionAttachmentReadRequest.model_validate(request.payload or {})
        with connect() as conn:
            question = request_row(conn, model.request_id)
            if question["kind"] != "operator_question":
                raise ValueError(
                    "operator_question_attachment_invalid: read an operator question attachment"
                )
            if (
                question.get("originator_actor_id") != actor_id
                and not requester_can_read(conn, question, actor_id)
                and authority_reason(conn, model.request_id, actor_id) is None
            ):
                return _error(
                    "permission_denied",
                    "operator_question_attachment_forbidden: read this question from an authorized Inbox",
                )
            result = read_attachment(conn, question, model.artifact_id)
            if isinstance(result, HandlerOutcome):
                return result
    except (ValueError, LookupError) as exc:
        return _error(
            "operator_question_attachment_invalid",
            str(exc),
        )
    except OSError as exc:
        return _error(
            "operator_question_attachment_unreadable",
            f"{exc}; restore access to the stored attachment and retry",
        )
    return HandlerOutcome(primary_success=True, result_payload=result)


def register(registry):
    from yoke_core.domain.handlers.qa_artifact_read import QaArtifactReadResponse

    registry.register(
        "decision_requests.attachment.read",
        handle_read,
        QuestionAttachmentReadRequest,
        QaArtifactReadResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["global"],
        side_effects=[],
        guardrails=["actor_required", "authority_union", "path_checked"],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
        minimum_serving_version="next-release",
    )
