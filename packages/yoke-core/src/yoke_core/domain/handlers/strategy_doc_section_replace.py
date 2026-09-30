"""Refresh one section of a strategy document without resending the rest.

A strategy document is one row, so the only write surface was the whole
body. Refreshing a "Live status" heading on a 70KB plan therefore meant
splicing the document by hand and sending all of it back — fifteen times in
one steering session — and every splice could carry an unrelated edit, or
drop one, with no way for the write to tell.

The write itself is not new. This composes the document's next content from
its stored content with one section replaced, then hands it to
:func:`~yoke_core.domain.strategy_docs.replace_doc`, so the claim
authorization, compare-and-swap, shrink guard, header validation,
revision history, and replaced event are the same ones the whole-document
path already has.

Compare-and-swap is always on, because a section replace is inherently
read-modify-write: the row the splice read is the base the write demands. A
caller's own ``base_updated_at`` is checked against that read first, so a
caller working from a revision the document has already moved past is
refused by name instead of having its edit silently rebased onto content it
never saw.
"""

from __future__ import annotations

from yoke_contracts.project_contract.strategy_doc_fields import StrategyDocFieldError

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome

from yoke_core.domain import strategy_docs as _docs
from yoke_core.domain.handlers.strategy_docs_claims import (
    CLAIM_ACQUIRE_RECIPE,
    session_holds_strategy_claim,
)
from yoke_core.domain.handlers.strategy_docs_models import (
    DocSectionReplaceRequest,
    DocReplaceResponse,
)
from yoke_core.domain.handlers.strategy_docs_project import resolve_request_project
from yoke_core.domain.strategy_doc_sections import (
    StrategyDocSectionMissingError,
    replace_section,
)
from yoke_core.domain.strategy_execution import (
    StrategyDocClaimAuthorizationError,
    authorize_strategy_doc_write,
)
from yoke_core.domain.work_processes import PROCESS_STRATEGIZE, conflict_group_for


def handle_doc_section_replace(request: FunctionCallRequest) -> HandlerOutcome:
    """Replace one heading's body, after checking the document's claim."""
    from yoke_core.domain.handlers.strategy_docs import (
        _bad_request,
        _err,
        _numeric_actor_id,
        _validate,
        emit_doc_replaced,
    )

    payload, err = _validate(
        request, DocSectionReplaceRequest, "strategy.doc.section_replace"
    )
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
        if not claimed_document and not session_holds_strategy_claim(
            conn, session_id, project.slug
        ):
            group = conflict_group_for(PROCESS_STRATEGIZE, project.slug)
            return _err(
                "strategy_claim_required",
                "strategy.doc.section_replace requires the calling session to "
                f"hold an active process work-claim in conflict group {group!r} "
                "(process STRATEGIZE or FEED). Acquire it first: "
                f"{CLAIM_ACQUIRE_RECIPE}",
            )
        try:
            stored = _docs.get_doc(conn, project.id, payload.slug)
        except _docs.UnknownStrategyDocError as exc:
            return _err("unknown_slug", str(exc))
        except _docs.StrategyDocMissingError as exc:
            return _err("doc_not_seeded", str(exc))
        base = str(stored.get("updated_at") or "")
        if payload.base_updated_at != base:
            return _err(
                "replace_conflict",
                f"strategy document {payload.slug!r} was last written at "
                f"{base!r}, not the {payload.base_updated_at!r} this section "
                "was authored against. Re-read it with `yoke strategy doc get "
                f"{payload.slug}`, re-apply the section, and retry.",
            )
        try:
            content = replace_section(
                str(stored.get("content") or ""),
                payload.heading,
                payload.content,
            )
        except StrategyDocSectionMissingError as exc:
            return _err("unknown_section", str(exc))
        try:
            actor_id = _numeric_actor_id(request.actor.actor_id)
            result = _docs.replace_doc(
                conn,
                project.id,
                payload.slug,
                content,
                actor_id,
                base_updated_at=base,
                force=payload.force,
                session_id=session_id,
            )
        except StrategyDocFieldError as exc:
            return _err("invalid_strategy_fields", str(exc))
        except _docs.EmptyStrategyDocError as exc:
            return _err("empty_content_refused", str(exc))
        except _docs.StrategyHeaderError as exc:
            return _err("invalid_strategy_header", str(exc))
        except _docs.StrategyDocShrinkError as exc:
            return _err("shrink_guard_refused", str(exc))
        except _docs.StrategyDocConflictError as exc:
            return _err("replace_conflict", str(exc))

    if not result.get("unchanged"):
        emit_doc_replaced(
            session_id=session_id,
            project=project,
            result=result,
            source="section_replace",
        )
    return HandlerOutcome(
        result_payload=DocReplaceResponse(
            project_id=project.id,
            project_slug=project.slug,
            **result,
        ).model_dump(),
        primary_success=True,
    )


__all__ = ["handle_doc_section_replace"]
