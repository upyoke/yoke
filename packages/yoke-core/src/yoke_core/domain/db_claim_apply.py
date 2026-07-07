"""Internal apply + composition + event emission for ``db_claim.amend``.

Owns the side-effecting half of the unified DB-claim amendment workflow:

* :class:`DbClaimAmendmentError` — operator-facing error class (canonical
  owner here; the front door re-exports it for stable importers).
* :class:`AmendmentResult` — successful-amendment return shape.
* :func:`_apply` — atomic two-field write + ``DbClaimAmended`` event
  emission.
* :func:`_compose_final_attestation` — caller-attestation + carried
  append-only fields + freshly stamped ``frozen_at``.
* :func:`_missing_required_authored_fields` — pre-merge-safe authored
  field presence check.
* :func:`_emit_amended_event` — native event emitter wrapper that
  guarantees no orphaned writes.
* :func:`_resolve_session_id` — env-var resolution chain for the event
  envelope.
* :func:`_safe_parse` — JSON → dict tolerant parser used by reads.

The front door :mod:`yoke_core.domain.db_claim` owns the validation +
demultiplexing of caller payloads and re-exports the public surface
(``amend``, ``read_claim``, ``DbClaimAmendmentError``, ``AmendmentResult``).
This module is the canonical owner for the apply / composition logic
sit behind that surface.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from yoke_core.domain import db_compatibility_attestation as dca
from yoke_core.domain import db_backend
from yoke_core.domain import db_helpers
from yoke_core.domain import db_mutation_profile as dmp


class DbClaimAmendmentError(ValueError):
    """Raised when an amendment payload fails validation or the item
    cannot be resolved.

    Error messages name the failing field and reason in a single
    operator-facing string so atomicity holds across both
    stored fields.
    """


@dataclass(frozen=True)
class AmendmentResult:
    """Outcome of a successful :func:`yoke_core.domain.db_claim.amend` call."""

    item_id: int
    previous_profile: Dict[str, Any]
    previous_attestation: Dict[str, Any]
    new_profile: Dict[str, Any]
    new_attestation: Dict[str, Any]
    reason: str
    event_id: Optional[str]


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _apply(
    conn: Any,
    item_id: int,
    new_profile: Dict[str, Any],
    caller_attestation: Dict[str, Any],
    reason: str,
    session_id: Optional[str],
) -> AmendmentResult:
    placeholder = _p(conn)
    row = conn.execute(
        "SELECT i.db_mutation_profile, i.db_compatibility_attestation, "
        "p.slug AS project "
        "FROM items i LEFT JOIN projects p ON p.id = i.project_id "
        f"WHERE i.id = {placeholder}",
        (item_id,),
    ).fetchone()
    if row is None:
        raise DbClaimAmendmentError(f"Item YOK-{item_id} not found")

    raw_profile = row["db_mutation_profile"] if hasattr(row, "keys") else row[0]
    raw_attestation = (
        row["db_compatibility_attestation"] if hasattr(row, "keys") else row[1]
    )
    project = row["project"] if hasattr(row, "keys") else row[2]
    previous_profile = _safe_parse(raw_profile) or {"state": dmp.STATE_NONE}
    previous_attestation = _safe_parse(raw_attestation) or {}

    final_attestation = _compose_final_attestation(
        new_profile=new_profile,
        caller_attestation=caller_attestation,
        previous_attestation=previous_attestation,
    )

    try:
        normalized_attestation = dca.validate(final_attestation)
    except dca.DbCompatibilityAttestationError as exc:
        raise DbClaimAmendmentError(
            f"db_compatibility_attestation (composed): {exc}"
        ) from exc

    now = db_helpers.iso8601_now()
    # Reviewed-negative attestation lives ON the profile: every amendment
    # that lands state="none" is, by construction, a validated operator
    # decision (validation already passed above), so the stamp records
    # that review directly in the stored JSON. The prose-vs-claim gate
    # reads these keys; the DbClaimAmended event is telemetry only.
    new_profile = dmp.stamp_reviewed_negative(new_profile, validated_at=now)
    profile_json = dmp.canonical_json(new_profile)
    attestation_json = dca.canonical_json(normalized_attestation)

    # The two-field write and event audit row are committed together
    # through the shared connection. Validation already ran; a SQL or
    # event-emission error here rolls back the amendment so successful
    # calls always leave both the claim and its DbClaimAmended evidence.
    try:
        conn.execute(
            f"UPDATE items SET db_mutation_profile = {placeholder}, "
            f"db_compatibility_attestation = {placeholder}, "
            f"updated_at = {placeholder} WHERE id = {placeholder}",
            (profile_json, attestation_json, now, item_id),
        )
        event_id = _emit_amended_event(
            conn=conn,
            item_id=item_id,
            project=str(project or "yoke"),
            session_id=_resolve_session_id(session_id),
            context={
                "previous_profile": previous_profile,
                "previous_attestation": previous_attestation,
                "new_profile": new_profile,
                "new_attestation": normalized_attestation,
                "reason": reason,
                "validation_result": "pass",
            },
            now=now,
        )
        if event_id is None:
            raise DbClaimAmendmentError(
                f"DbClaimAmended event emission failed for YOK-{item_id}; "
                "claim was not written"
            )
        conn.commit()
    except db_backend.database_error_types(conn) as exc:
        conn.rollback()
        raise DbClaimAmendmentError(
            f"amendment write failed for YOK-{item_id}: {exc}"
        ) from exc
    except DbClaimAmendmentError:
        conn.rollback()
        raise

    return AmendmentResult(
        item_id=item_id,
        previous_profile=previous_profile,
        previous_attestation=previous_attestation,
        new_profile=new_profile,
        new_attestation=normalized_attestation,
        reason=reason,
        event_id=event_id,
    )


def _compose_final_attestation(
    *,
    new_profile: Dict[str, Any],
    caller_attestation: Dict[str, Any],
    previous_attestation: Dict[str, Any],
) -> Dict[str, Any]:
    """Assemble the final attestation shape the workflow will persist.

    For ``state="none"`` the attestation is fully cleared (including
    any prior ``frozen_at``). For ``state="declared"``
    the caller-supplied authored fields stand, append-only companions
    (outcomes / escalations) are carried forward from the current row,
    and a fresh ``frozen_at`` is stamped.
    """
    if new_profile["state"] == dmp.STATE_NONE:
        return {}

    final: Dict[str, Any] = dict(caller_attestation)
    if "rehearsal_outcomes" in previous_attestation:
        final.setdefault(
            "rehearsal_outcomes",
            copy.deepcopy(previous_attestation["rehearsal_outcomes"]),
        )
    if "class_escalations" in previous_attestation:
        final.setdefault(
            "class_escalations",
            copy.deepcopy(previous_attestation["class_escalations"]),
        )
    final[dca.FREEZE_FIELD] = db_helpers.iso8601_now()
    return final


def _missing_required_authored_fields(attestation: Dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field in sorted(dca.AUTHORED_FIELDS):
        value = attestation.get(field)
        if value is None:
            missing.append(field)
            continue
        if isinstance(value, str) and not value.strip():
            missing.append(field)
        elif isinstance(value, (list, dict, tuple)) and len(value) == 0:
            missing.append(field)
    return missing


def _emit_amended_event(
    *,
    conn: Any,
    item_id: int,
    project: str,
    session_id: str,
    context: Dict[str, Any],
    now: str,
) -> Optional[str]:
    """Emit a ``DbClaimAmended`` event via the native event emitter.

    Returns the event ID on success and ``None`` when the events
    infrastructure refuses or cannot persist the event. The caller
    treats ``None`` as fatal so successful amendments always carry an
    audit event.
    """
    try:
        from yoke_core.domain.events import emit_event as _native_emit
    except ImportError:
        return None

    try:
        envelope = _native_emit(
            "DbClaimAmended",
            event_kind="workflow",
            event_type="db_claim_amendment",
            source_type="system",
            session_id=session_id,
            severity="INFO",
            outcome="completed",
            project=project,
            item_id=item_id,
            context=context,
            created_at=now,
            conn=conn,
        )
    except Exception:
        return None
    if not envelope.ok:
        return None
    return envelope.event_id


def _resolve_session_id(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    from yoke_core.domain.session_ambient_identity import (
        resolve_ambient_session_id,
    )

    return resolve_ambient_session_id() or ""


def _safe_parse(raw: Any) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


__all__ = [
    "AmendmentResult",
    "DbClaimAmendmentError",
    "_apply",
    "_compose_final_attestation",
    "_emit_amended_event",
    "_missing_required_authored_fields",
    "_resolve_session_id",
    "_safe_parse",
]
