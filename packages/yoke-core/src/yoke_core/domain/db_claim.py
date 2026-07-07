"""Unified DB-claim amendment workflow.

Sanctioned surface for reading, validating, and updating a ticket's DB
claim as a single unit over the two existing storage fields
(``db_mutation_profile`` and ``db_compatibility_attestation``).

Callers — ``/yoke idea``, ``/yoke refine``, ``/yoke advance``,
``/yoke polish``, and any agent discovering DB mutation late — go
through :func:`amend` rather than writing the two JSON fields directly.
Per-field writes that skip this workflow remain structurally valid but
are reserved as internal implementation helpers.

Invariants:

* **Atomic** — validation failure on either half leaves both fields
  unchanged and emits no ``DbClaimAmended`` event.
* **No freeze on negative claims** — writing ``state="none"`` clears any
  prior ``frozen_at`` stamp; only declared claims carry a freeze
  timestamp.
* **History via events** — every successful amendment emits a
  ``DbClaimAmended`` event whose envelope carries the previous claim
  summary, new claim summary, actor/session, reason, and timestamp.
  No dedicated amendment-history table exists.
* **Upsert** — ``amend`` accepts a write against a currently-absent
  claim, so ``/yoke idea`` late-classification and subsequent
  amendments use the same entrypoint.

Input shape accepted by :func:`amend`::

    {
        "state": "none" | "declared",
        # Profile side (state="declared" only):
        "model_name": "primary",
        "mutation_intent": "apply" | "retire",
        "migration_modules": ["..."],
        "compatibility_class": "pre_merge_safe" | "pre_merge_breaking",
        "affected_surfaces": [...],
        "schema_kinds": [...],
        "data_kinds": [...],
        "count_preserving": true,
        # Attestation side (state="declared" + pre_merge_safe all required):
        "pre_merge_readers_writers": [...],
        "invariants": [...],
        "rehearsal_commands": [...],
        "residual_risk_notes": "...",
    }

The four authored attestation fields are required inline when
``compatibility_class="pre_merge_safe"``. ``frozen_at``,
``rehearsal_outcomes``, and ``class_escalations`` are reserved — the
workflow manages them internally.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain import db_compatibility_attestation as dca
from yoke_core.domain import db_helpers
from yoke_core.domain import db_mutation_profile as dmp
from yoke_core.domain.db_claim_apply import (
    AmendmentResult,
    DbClaimAmendmentError,
    _apply,
    _missing_required_authored_fields,
    _safe_parse,
)


# Keys that belong to the profile half of the unified payload.
_PROFILE_KEYS = frozenset({
    "state",
    "model_name",
    "mutation_intent",
    "migration_modules",
    "compatibility_class",
    "migration_strategy",
    "migration_strategy_justification",
    "schema_kinds",
    "data_kinds",
    "affected_surfaces",
    "count_preserving",
})

# Caller-supplied attestation keys. ``frozen_at`` is workflow-managed;
# ``rehearsal_outcomes`` and ``class_escalations`` are append-only and
# carried over from the current row on every amendment.
_ATTESTATION_KEYS = frozenset({
    "pre_merge_readers_writers",
    "invariants",
    "rehearsal_commands",
    "residual_risk_notes",
})

# Fields the workflow refuses on input (internal management). The
# reviewed-negative attestation pair is stamped by the apply layer when
# an amendment lands ``state="none"`` — callers never author it.
_RESERVED_KEYS = frozenset({
    dca.FREEZE_FIELD,
    "rehearsal_outcomes",
    "class_escalations",
    dmp.REVIEWED_NEGATIVE_FIELD,
    dmp.REVIEWED_VALIDATED_AT_FIELD,
})


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def amend(
    item_id: int,
    claim_payload: Mapping[str, Any],
    *,
    reason: str,
    conn: Optional[Any] = None,
    session_id: Optional[str] = None,
) -> AmendmentResult:
    """Apply a unified DB-claim amendment atomically.

    Validates *claim_payload* as a whole, demultiplexes it across the
    two stored JSON fields, writes both atomically, and emits a
    ``DbClaimAmended`` event. Raises :class:`DbClaimAmendmentError`
    when the payload fails validation, required fields are missing for
    the compatibility class, or the target item cannot be resolved.

    Args:
        item_id: Numeric backlog item ID. ``YOK-N`` prefixes must be
            stripped before calling.
        claim_payload: Unified claim dict — profile and attestation
            fields combined.
        reason: Non-empty operator-facing justification persisted on
            the amendment event.
        conn: Optional pre-opened DB connection. When omitted, the
            workflow opens a short-lived connection via
            :func:`db_helpers.connect`.
        session_id: Optional session ID override. Falls back to
            ``YOKE_SESSION_ID`` / ``CLAUDE_SESSION_ID`` /
            ``CODEX_THREAD_ID`` in that order.

    Returns:
        An :class:`AmendmentResult` with previous and new claim shapes
        plus the emitted event ID.
    """
    if not isinstance(item_id, int) or item_id <= 0:
        raise DbClaimAmendmentError(
            f"item_id must be a positive integer; got {item_id!r}"
        )
    if not isinstance(claim_payload, Mapping):
        raise DbClaimAmendmentError(
            "claim_payload must be a dict; "
            f"got {type(claim_payload).__name__}"
        )
    if not isinstance(reason, str) or not reason.strip():
        raise DbClaimAmendmentError(
            "reason must be a non-empty string describing why the "
            "claim is being amended"
        )

    reserved = _RESERVED_KEYS & set(claim_payload.keys())
    if reserved:
        raise DbClaimAmendmentError(
            f"amendment payload must not supply reserved field(s): "
            f"{sorted(reserved)}. These are managed by Yoke, not "
            "callers."
        )

    unknown = set(claim_payload.keys()) - (_PROFILE_KEYS | _ATTESTATION_KEYS)
    if unknown:
        valid = sorted(_PROFILE_KEYS | _ATTESTATION_KEYS)
        raise DbClaimAmendmentError(
            f"amendment payload has unknown keys: {sorted(unknown)}. "
            f"Valid keys: {valid}"
        )

    profile_input = {
        k: v for k, v in claim_payload.items() if k in _PROFILE_KEYS
    }
    attestation_input = {
        k: v for k, v in claim_payload.items() if k in _ATTESTATION_KEYS
    }

    # Profile structural validation.
    try:
        new_profile = dmp.validate(profile_input)
    except dmp.DbMutationProfileError as exc:
        raise DbClaimAmendmentError(f"db_mutation_profile: {exc}") from exc

    # Attestation structural validation + cross-field requirements.
    if new_profile["state"] == dmp.STATE_NONE:
        if attestation_input:
            raise DbClaimAmendmentError(
                "state='none' claims do not carry attestation fields; "
                f"caller supplied: {sorted(attestation_input.keys())}"
            )
        validated_attestation_input: Dict[str, Any] = {}
    else:
        try:
            validated_attestation_input = dca.validate(attestation_input)
        except dca.DbCompatibilityAttestationError as exc:
            raise DbClaimAmendmentError(
                f"db_compatibility_attestation: {exc}"
            ) from exc
        if new_profile.get("compatibility_class") == dmp.COMPATIBILITY_PRE_MERGE_SAFE:
            missing = _missing_required_authored_fields(validated_attestation_input)
            if missing:
                raise DbClaimAmendmentError(
                    "db_compatibility_attestation: "
                    "compatibility_class='pre_merge_safe' requires "
                    f"non-empty authored fields; missing/empty: {missing}"
                )

    if conn is None:
        with db_helpers.connect() as owned:
            return _apply(
                owned,
                item_id,
                new_profile,
                validated_attestation_input,
                reason,
                session_id,
            )
    return _apply(
        conn,
        item_id,
        new_profile,
        validated_attestation_input,
        reason,
        session_id,
    )


def read_claim(
    item_id: int,
    *,
    conn: Optional[Any] = None,
) -> Dict[str, Any]:
    """Return the item's current DB claim as a structured dict.

    Returns ``{"profile": {...}, "attestation": {...}}`` reflecting the
    current stored shapes. Missing/empty fields normalize to the
    negative default (``{"state":"none"}``) and empty attestation
    (``{}``) respectively.
    """
    def _read(c: Any) -> Dict[str, Any]:
        placeholder = _p(c)
        row = c.execute(
            "SELECT db_mutation_profile, db_compatibility_attestation "
            f"FROM items WHERE id = {placeholder}",
            (item_id,),
        ).fetchone()
        if row is None:
            raise DbClaimAmendmentError(f"Item YOK-{item_id} not found")
        raw_profile = row["db_mutation_profile"] if hasattr(row, "keys") else row[0]
        raw_attestation = (
            row["db_compatibility_attestation"] if hasattr(row, "keys") else row[1]
        )
        return {
            "profile": _safe_parse(raw_profile) or {"state": dmp.STATE_NONE},
            "attestation": _safe_parse(raw_attestation) or {},
        }

    if conn is not None:
        return _read(conn)
    with db_helpers.connect() as owned:
        return _read(owned)


__all__ = [
    "AmendmentResult",
    "DbClaimAmendmentError",
    "amend",
    "read_claim",
]
