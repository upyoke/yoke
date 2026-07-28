"""Claim-aware strategy document replacement handler."""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome

from yoke_core.domain import strategy_docs as _docs
from yoke_core.domain.handlers.strategy_docs_claims import (
    CLAIM_ACQUIRE_RECIPE,
    session_holds_strategy_claim,
)
from yoke_core.domain.handlers.strategy_docs_models import (
    DocReplaceRequest,
    DocReplaceResponse,
)
from yoke_core.domain.handlers.strategy_docs_project import (
    resolve_request_project,
)
from yoke_core.domain.strategy_execution import (
    StrategyDocClaimAuthorizationError,
    authorize_strategy_doc_write,
)
from yoke_core.domain.work_processes import (
    PROCESS_STRATEGIZE,
    conflict_group_for,
)


def handle_doc_replace(request: FunctionCallRequest) -> HandlerOutcome:
    """Replace one document after checking its item or process claim."""
    from yoke_core.domain.handlers.strategy_docs import (
        _bad_request,
        _err,
        _numeric_actor_id,
        _validate,
        emit_doc_replaced,
    )

    payload, err = _validate(request, DocReplaceRequest, "strategy.doc.replace")
    if err is not None:
        return err
    session_id = request.actor.session_id
    if not session_id:
        return _bad_request(
            "actor.session_id is required",
            jsonpath="$.actor.session_id",
        )

    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        project, perr = resolve_request_project(conn, request)
        if perr is not None:
            return perr
        try:
            claimed_document = authorize_strategy_doc_write(
                conn,
                project_id=project.id,
                slug=payload.slug,
                session_id=session_id,
            )
        except StrategyDocClaimAuthorizationError as exc:
            return _err("strategy_document_claim_denied", str(exc))
        if (
            not claimed_document
            and not session_holds_strategy_claim(conn, session_id, project.slug)
        ):
            group = conflict_group_for(PROCESS_STRATEGIZE, project.slug)
            return _err(
                "strategy_claim_required",
                "strategy.doc.replace requires the calling session to hold "
                f"an active process work-claim in conflict group {group!r} "
                "(process STRATEGIZE or FEED). Acquire it first: "
                f"{CLAIM_ACQUIRE_RECIPE}",
            )
        try:
            actor_id = _numeric_actor_id(request.actor.actor_id)
            result = _docs.replace_doc(
                conn,
                project.id,
                payload.slug,
                payload.content,
                actor_id,
                base_updated_at=payload.base_updated_at,
                force=payload.force,
                session_id=session_id,
            )
            if actor_id is not None and not result.get("unchanged"):
                from yoke_core.domain.strategy_review_requests import (
                    ensure_current_strategy_revision_review,
                )

                ensure_current_strategy_revision_review(
                    conn,
                    project_id=project.id,
                    slug=payload.slug,
                    originator_actor_id=actor_id,
                    reviewer_actor_id=payload.reviewer_actor_id,
                    session_id=session_id,
                )
        except _docs.UnknownStrategyDocError as exc:
            return _err("unknown_slug", str(exc))
        except _docs.StrategyDocMissingError as exc:
            return _err("doc_not_seeded", str(exc))
        except _docs.EmptyStrategyDocError as exc:
            return _err("empty_content_refused", str(exc))
        except _docs.StrategyHeaderError as exc:
            return _err("invalid_strategy_header", str(exc))
        except _docs.StrategyDocShrinkError as exc:
            return _err("shrink_guard_refused", str(exc))
        except _docs.StrategyDocConflictError as exc:
            return _err("replace_conflict", str(exc))
        except LookupError as exc:
            return _err("reviewer_not_found", str(exc))

    if not result.get("unchanged"):
        emit_doc_replaced(
            session_id=session_id,
            project=project,
            result=result,
            source="replace",
        )
    return HandlerOutcome(
        result_payload=DocReplaceResponse(
            project_id=project.id,
            project_slug=project.slug,
            **result,
        ).model_dump(),
        primary_success=True,
    )


__all__ = ["handle_doc_replace"]
