"""Claim verification helpers for the function-call dispatcher.

Extracted from :mod:`yoke_function_dispatch` to keep the dispatcher's
main routing flow within the file-line budget. Each ``claim_required_kind``
maps to one verification predicate:

- ``"item"`` / ``"epic"`` — consult the canonical session-claim lookup
  for the target item / epic id; require the actor's ``session_id`` to
  match the active claim row.
- ``"self_only"`` — read ``work_claims`` by id; require the actor to own
  the claim row.
- ``"steering"`` — require a live steering seat covering the target scope.
- ``"qa_subject"`` — delegate to
  :func:`yoke_core.domain.yoke_function_dispatch_qa_claims.qa_subject_claim_verdict`,
  which accepts a live item claim or the claim a long gate run bound at
  its start.

Tests monkeypatch :func:`who_claims_for_item` and :func:`steering_seat_for_request`
to inject synthetic rows without touching the live DB.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)
from yoke_core.domain.yoke_function_dispatch_qa_claims import (
    qa_subject_claim_verdict as _qa_subject_claim_verdict,
    resolve_deployment_member_item_id as _resolve_deployment_member_item_id,
    resolve_qa_requirement_item_id as _resolve_qa_requirement_item_id,
)
from yoke_core.domain.claim_recovery import (
    canonical_item_ref as _claim_recovery_item_ref,
)
from yoke_core.domain.yoke_function_dispatch_claim_evidence import (
    ClaimVerificationEvidence,
    WORK_CLAIM_AUTHORITY,
    allow_claim_verification,
    begin_claim_verification,
)
from yoke_core.domain.yoke_function_dispatch_claims_resolve import (
    claim_row_for_id as _claim_row_for_id,
    session_claim_id_for_target as _session_claim_id_for_target,
)
from yoke_core.domain.yoke_function_registry import RegistryEntry
from yoke_core.domain.project_identity_item_ref import item_ref_for_id


def who_claims_for_item(item_id: int) -> Optional[Dict[str, Any]]:
    """Return the active item-target claim, if one can be read."""
    try:
        from yoke_core.domain import db_helpers
        from yoke_core.domain.sessions_queries_lookup import (
            get_claim_for_work_unit,
        )
    except Exception:
        return None
    try:
        with db_helpers.connect() as conn:
            return get_claim_for_work_unit(conn, item_id=str(item_id))
    except Exception:
        return None


def steering_seat_for_request(entry: RegistryEntry, request: FunctionCallRequest):
    """Resolve the actual target and check the caller's covering live seat."""
    from yoke_core.domain import db_helpers
    from yoke_core.domain.function_target_resolution import resolve_project_context
    from yoke_core.domain.steering_scope_membership import item_coverage_target
    from yoke_core.domain.session_steering_authority import covering_session_seat

    with db_helpers.connect() as conn:
        project = resolve_project_context(conn, entry, request)
        if project is None:
            return None, "<unresolved>"
        item_id = request.target.item_id or request.target.epic_id
        path_claim_id = (
            request.payload.get("path_claim_id") or request.target.path_claim_id
        )
        if path_claim_id is not None:
            from yoke_core.domain.yoke_function_dispatch_claims_resolve import (
                _placeholder,
            )

            row = conn.execute(
                f"SELECT owner_item_id FROM path_claims WHERE id={_placeholder(conn)}",
                (int(path_claim_id),),
            ).fetchone()
            item_id = row[0] if row is not None else None
        target = item_coverage_target(conn, project_id=project[0], item_id=item_id)
        return covering_session_seat(
            conn,
            caller_session_id=request.actor.session_id,
            target=target,
        ), project[1]


def _claim_error(
    request: FunctionCallRequest,
    function_id: str,
    version: str,
    code: str,
    message: str,
    *,
    recovery_hint: Optional[str] = None,
) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=function_id,
        version=version,
        request_id=request.request_id,
        result={},
        warnings=[],
        error=FunctionError(
            code=code,
            message=message,
            recovery_hint=recovery_hint,
        ),
        event_ids=[],
    )


def _allow_resolved_self_claim(
    evidence: Optional[ClaimVerificationEvidence],
    target: Any,
    actor_session: str,
    resolved: int,
) -> None:
    target.claim_id = resolved
    allow_claim_verification(
        evidence,
        authority=WORK_CLAIM_AUTHORITY,
        claim_id=resolved,
        holder_session_id=actor_session,
    )


def verify_claim(
    entry: RegistryEntry,
    request: FunctionCallRequest,
    *,
    evidence: Optional[ClaimVerificationEvidence] = None,
) -> Optional[FunctionCallResponse]:
    """Return an error response unless the registry-directed check passes."""
    begin_claim_verification(evidence, entry, request)
    kind = entry.claim_required_kind
    if kind is None:
        return None
    actor_session = request.actor.session_id
    target = request.target
    fid = entry.function_id
    ver = entry.version

    if kind == "qa_subject":
        allowed, code, message = _qa_subject_claim_verdict(request)
        if allowed:
            allow_claim_verification(evidence, authority="qa_subject_policy")
            return None
        return _claim_error(request, fid, ver, code or "claim_required", message or "")

    if kind in ("item", "epic"):
        target_id = target.item_id if kind == "item" else target.epic_id
        if (
            target_id is None
            and kind == "item"
            and target.kind == "qa_requirement"
            and target.qa_requirement_id is not None
        ):
            resolved, err_code, err_msg = _resolve_qa_requirement_item_id(
                target.qa_requirement_id
            )
            if err_code is not None:
                return _claim_error(request, fid, ver, err_code, err_msg or "")
            target_id = resolved
        if target_id is None and kind == "item" and target.kind == "deployment_run":
            # An item-scoped deployment stage names its member in the
            # payload, not in target.item_id; that member is the thing a
            # caller holds a claim on.
            payload = request.payload if isinstance(request.payload, dict) else {}
            resolved, err_code, err_msg = _resolve_deployment_member_item_id(
                payload.get("deployment_member")
            )
            if err_code is not None:
                return _claim_error(request, fid, ver, err_code, err_msg or "")
            target_id = resolved
        if target_id is None:
            return _claim_error(
                request,
                fid,
                ver,
                "claim_required",
                f"claim_required_kind={kind!r} but target id is missing",
            )
        row = who_claims_for_item(int(target_id))
        claim_session = str((row or {}).get("session_id") or "")
        if not row or claim_session != actor_session:
            public_ref = (
                _claim_recovery_item_ref(int(target_id)) if kind == "item" else None
            )
            recovery = (
                f'yoke claims work acquire --item {public_ref} --reason "<intent>"'
                if public_ref
                else "acquire the required claim before retrying"
            )
            target_ref = public_ref or str(target_id)
            return _claim_error(
                request,
                fid,
                ver,
                "claim_required",
                f"no active claim by session {actor_session!r} on "
                f"{kind} {target_ref}; acquire one first: "
                f"{recovery}",
            )
        allow_claim_verification(
            evidence,
            authority=WORK_CLAIM_AUTHORITY,
            target_item_id=int(target_id) if kind == "item" else None,
            target_epic_id=int(target_id) if kind == "epic" else None,
            claim_id=row.get("id"),
            holder_session_id=claim_session,
        )
        return None

    if kind == "self_only":
        claim_id = target.claim_id
        payload = request.payload or {}
        process_key = payload.get("process_key")
        if claim_id is None and (target.kind in ("item", "epic_task") or process_key):
            resolved = _session_claim_id_for_target(
                target,
                actor_session,
                process_key=process_key,
                project=str(
                    request.options.get("authorized_project_id")
                    or payload.get("project")
                    or ""
                ),
            )
            if resolved is None:
                if process_key:
                    shape = f"process {process_key}"
                elif target.kind == "item":
                    shape = item_ref_for_id(target.item_id)
                else:
                    shape = f"epic_task ({target.epic_id}, {target.task_num})"
                return _claim_error(
                    request,
                    fid,
                    ver,
                    "claim_required",
                    f"no active claim by session {actor_session!r} on "
                    f"{shape}; pass --claim-id explicitly or acquire one "
                    "first: yoke claims work acquire",
                )
            # Lookup filters on actor session — resolution is ownership proof.
            _allow_resolved_self_claim(
                evidence,
                target,
                actor_session,
                resolved,
            )
            return None
        if claim_id is None:
            return _claim_error(
                request,
                fid,
                ver,
                "claim_required",
                "claim_required_kind='self_only' but target.claim_id is missing",
            )
        row = _claim_row_for_id(int(claim_id))
        owner = str((row or {}).get("session_id") or "")
        if owner != actor_session:
            return _claim_error(
                request,
                fid,
                ver,
                "claim_required",
                f"claim {claim_id} not held by session {actor_session!r}; "
                f"acquire your own claim with: "
                f"yoke claims work acquire "
                f'--item "YOK-<id>" --reason "<intent>"',
            )
        allow_claim_verification(
            evidence,
            authority=WORK_CLAIM_AUTHORITY,
            claim_id=row.get("id"),
            holder_session_id=owner,
        )
        return None

    if kind == "steering":
        from yoke_core.domain.session_steering_authority import (
            steering_authority_message,
        )

        seat, project = steering_seat_for_request(entry, request)
        if seat is None:
            return _claim_error(
                request,
                fid,
                ver,
                "steering_seat_required",
                f"{fid} {steering_authority_message(project)}",
                recovery_hint="Acquire the covering steering seat or route via yoke say --steering.",
            )
        allow_claim_verification(
            evidence,
            authority="steering",
            claim_id=seat["claim_id"],
            holder_session_id=actor_session,
        )
        return None

    # Defensive — registry validation makes this unreachable.
    return _claim_error(
        request,
        fid,
        ver,
        "claim_required",
        f"unknown claim_required_kind {kind!r}",
    )


__all__ = [
    "who_claims_for_item",
    "steering_seat_for_request",
    "verify_claim",
    "_resolve_qa_requirement_item_id",
    "_session_claim_id_for_target",
    "_claim_row_for_id",
]
