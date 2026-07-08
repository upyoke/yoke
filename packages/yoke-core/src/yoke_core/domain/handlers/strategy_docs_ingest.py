"""Handler for ``strategy.ingest.run`` — CAS write-back from edited renders.

The operator's editor bridge: parse each shipped file's header base
marker, skip docs whose body hash matches the header (no-op), write
changed docs via compare-and-swap on the header's base ``updated_at``
(rowcount 0 → typed ``ingest_conflict`` teaching the re-render +
``git diff`` recovery), then return the re-rendered file text for
exactly the written docs so the CALLER advances their headers on disk.
Headerless/mangled files are refused with a typed error naming the
file; ``--dry-run`` previews per-doc changed/unchanged/conflict with
line deltas and writes nothing.

File I/O is the caller's (12942): the payload ships ``files`` entries
``{slug, path, text}`` read client-side
(:func:`yoke_core.domain.strategy_docs_ingest.read_ingest_files`),
and the response's ``file_text`` per written doc is what the CLI writes
back — the handler never touches a filesystem path, so the same
envelope works in-process and over https where the server has no
checkout. ``target_root`` rides along as message context for the
conflict-recovery teaching only.

Per-project: the target project resolves like every strategy handler
(``target.project_id`` → session inference → typed error), and every
read, CAS write, claim check, and re-render is scoped to that project.

Claim interplay: ingest never *requires* the STRATEGIZE/FEED process
claim (no lock ceremony for an editor fix), but it BOUNCES when a
*foreign* session holds the project's live claim — a strategize/feed
session owns that project's write window, and racing it from a file
edit is exactly the lost update the claim exists to prevent. A direct
terminal ingest with no harness session has no matching holder identity,
so any live claim is foreign; the claim holder itself may ingest. With
replace claim-gated and CAS-checked and
ingest foreign-claim-refused and CAS-checked, no pair of writers can
silently interleave. Events share the ``StrategyDocReplaced`` name with
``source=ingest`` (replace emits ``source=replace``).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_core.domain import strategy_docs as _docs
from yoke_core.domain import strategy_docs_ingest as _ingest
from yoke_core.domain.handlers.strategy_docs import (
    STRATEGY_DOC_REPLACED_EVENT_NAME,
    _err,
    _numeric_actor_id,
    _validate,
    emit_doc_replaced,
    foreign_strategy_claim_holder,
)
from yoke_core.domain.handlers.strategy_docs_project import (
    resolve_request_project,
)
from yoke_core.domain.strategy_docs_header import StrategyHeaderError
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class IngestFileEntry(BaseModel):
    slug: str = Field(..., min_length=1, description="Strategy doc slug.")
    path: str = Field(
        "", description="Client-side file path (error-message context only).",
    )
    text: str = Field(
        ..., description="The rendered file's full text (header line + body).",
    )


class IngestRequest(BaseModel):
    files: List[IngestFileEntry] = Field(
        ...,
        min_length=1,
        description=(
            "Rendered files read client-side (read_ingest_files); the "
            "handler validates and CAS-writes from these texts."
        ),
    )
    dry_run: bool = Field(
        False,
        description="Preview per-doc changed/unchanged/conflict; write nothing.",
    )
    target_root: Optional[str] = Field(
        None,
        description=(
            "Caller checkout root, message context for conflict-recovery "
            "teaching only — the handler does no file I/O."
        ),
    )


class IngestResponse(BaseModel):
    project_id: int
    project_slug: str
    target_root: str
    dry_run: bool
    docs: List[Dict[str, Any]] = Field(default_factory=list)
    written: int = 0
    unchanged: int = 0
    conflicts: int = 0


def _counts(docs: List[Dict[str, Any]]) -> Dict[str, int]:
    return {
        "written": sum(1 for d in docs if d["status"] == "written"),
        "unchanged": sum(1 for d in docs if d["status"] == "unchanged"),
        "conflicts": sum(1 for d in docs if d["status"] == "conflict"),
    }


def handle_ingest(request: FunctionCallRequest) -> HandlerOutcome:
    payload, err = _validate(request, IngestRequest, "strategy.ingest.run")
    if err is not None:
        return err
    session_id = request.actor.session_id or ""
    target_root = str(payload.target_root or "<your checkout>")

    from yoke_core.domain.actor_render import actor_render_label
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.strategy_docs_header import render_file_text

    ingest_label: str | None = None
    try:
        with connect() as conn:
            project, perr = resolve_request_project(conn, request)
            if perr is not None:
                return perr
            if not payload.dry_run:
                holder = foreign_strategy_claim_holder(
                    conn, session_id, project.slug,
                )
                if holder is not None:
                    return _err(
                        "ingest_blocked_by_live_process_claim",
                        "a strategize/feed session currently owns project "
                        f"{project.slug!r}'s strategy write window (session "
                        f"{holder!r} holds the live STRATEGIZE/FEED process "
                        "work-claim) — ingesting file edits under it risks "
                        "the lost update the claim exists to prevent. Wait "
                        "for that session to finish (or release its claim), "
                        "re-render to pick up its writes, re-apply your "
                        "edits, then ingest again.",
                    )
            plans = _ingest.plan_ingest(
                conn, project_id=project.id,
                files=[entry.model_dump() for entry in payload.files],
            )
            if payload.dry_run:
                docs = _ingest.dry_run_report(plans)
            else:
                actor_id = _numeric_actor_id(request.actor.actor_id)
                docs = _ingest.execute_ingest(
                    conn, plans, project_id=project.id, actor_id=actor_id,
                )
                # All docs in one ingest share the requesting actor; resolve
                # its display label once (inside the live conn) so the
                # write-back header matches render_file_map's output.
                ingest_label = actor_render_label(conn, actor_id)
    except _docs.UnknownStrategyDocError as exc:
        return _err("unknown_slug", str(exc))
    except _docs.StrategyDocMissingError as exc:
        return _err("doc_not_seeded", str(exc))
    except _docs.EmptyStrategyDocError as exc:
        return _err("empty_content_refused", str(exc))
    except StrategyHeaderError as exc:
        return _err("ingest_header_invalid", str(exc))

    bodies = {plan.slug: plan.file_body for plan in plans}
    archived_by_slug = {plan.slug: plan.archived for plan in plans}
    for doc in docs:
        if doc["status"] != "written":
            continue
        # The caller advances the written docs' headers on disk from
        # this text so a re-run no-ops; unchanged and conflicted files
        # are never returned (a conflicted file holds the operator's
        # only copy of their edits). ``archived`` rides along so the
        # write-back re-render lands an edited archived doc back under
        # .yoke/strategy/archive/ instead of the active location.
        doc["file_text"] = render_file_text(
            doc["slug"], doc["updated_at"], bodies[doc["slug"]],
            updated_by=ingest_label,
        )
        doc["archived"] = archived_by_slug.get(doc["slug"], False)
        emit_doc_replaced(
            session_id=session_id, project=project, result=doc,
            source="ingest",
        )

    response = IngestResponse(
        project_id=project.id,
        project_slug=project.slug,
        target_root=target_root,
        dry_run=payload.dry_run,
        docs=docs,
        **_counts(docs),
    )
    conflicted = [d["slug"] for d in docs if d["status"] == "conflict"]
    if conflicted and not payload.dry_run:
        # Per-doc outcomes ride along so the caller sees what DID land.
        return HandlerOutcome(
            result_payload=response.model_dump(),
            primary_success=False,
            error=FunctionError(
                code="ingest_conflict",
                message=_ingest.conflict_teaching(conflicted, target_root),
            ),
        )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "strategy.ingest.run",
        "handler": handle_ingest,
        "request_model": IngestRequest,
        "response_model": IngestResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.strategy_docs_ingest",
        "target_kinds": ["global"],
        "side_effects": ["db_write", "event_emit"],
        "emitted_event_names": [STRATEGY_DOC_REPLACED_EVENT_NAME],
        "guardrails": [
            "render_header_required",
            "compare_and_swap_base",
            "foreign_process_claim_refused",
            "client_side_file_io",
        ],
        "adapter_status": "live",
        "claim_required_kind": None,
        "ambient_session_required": False,
    },
]


__all__ = [
    "IngestFileEntry",
    "IngestRequest",
    "IngestResponse",
    "REGISTRATIONS",
    "handle_ingest",
]
