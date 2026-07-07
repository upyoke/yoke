"""Typed owner_kind for path claims — constants, validation, classification.

A path-claim row carries two orthogonal facts about who is responsible
for it:

1. **Ownership** — which subject owns the claimed paths right now.
   Authority answer. One of three kinds:

   - ``owner_kind = "item"`` — the item owns the implementation/planning
     scope. Survives the registering session ending. ``owner_item_id``
     is required and references ``items(id)``.
   - ``owner_kind = "session"`` — a live harness session owns paths
     outside item work (true "orphan/session" claim). When the session
     ends, the claim's authority ends. ``owner_session_id`` is required
     and references ``harness_sessions(session_id)``.
   - ``owner_kind = "process"`` — a work/process claim owns paths
     outside the item-owned model. ``owner_work_claim_id`` is required
     and references ``work_claims(id)``.

2. **Provenance** — which actor / session registered (or amended) the
   row. Always populated regardless of owner_kind. The board and active-
   claim readers must NOT use provenance to decide who owns the paths.

   - ``registered_by_actor_id`` — actor that registered the row.
   - ``registered_by_session_id`` — session that registered the row
     (may be ``NULL`` when the registration happened without a live
     harness session — e.g., a background scheduler).

The legacy columns ``actor_id``, ``session_id``, ``item_id``, and
``work_claim_id`` remain on the table during the cutover for backwards-
compatibility. They are populated alongside the typed owner columns by
writers and the backfill migration. **New readers MUST prefer the
typed owner columns** — ``HC-path-claim-owner-kind`` flags non-terminal
rows that do not satisfy the typed contract.

This module owns:

- The closed enum of valid owner kinds.
- ``validate_owner`` — refuse owner_kind / owner-field combos that
  break the typed contract.
- ``classify_backfill`` — deterministic classification of a legacy row
  by its non-typed columns, used by the one-shot migration and by the
  doctor HC. Refuses to guess on contradictory rows.
- ``owner_columns_for_kind`` — for writers, which legacy + typed
  columns to populate given an owner kind.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


OWNER_KIND_ITEM = "item"
OWNER_KIND_SESSION = "session"
OWNER_KIND_PROCESS = "process"

VALID_OWNER_KINDS: tuple[str, ...] = (
    OWNER_KIND_ITEM,
    OWNER_KIND_SESSION,
    OWNER_KIND_PROCESS,
)


class OwnerError(Exception):
    """Base class for typed owner failures."""


class InvalidOwnerKind(OwnerError):
    """``owner_kind`` is not one of :data:`VALID_OWNER_KINDS`."""


class InvalidOwnerCombination(OwnerError):
    """The owner-field combination does not satisfy the typed contract."""


class ContradictoryOwnerSignals(OwnerError):
    """A legacy row carries mutually exclusive ownership signals."""


@dataclass(frozen=True)
class Owner:
    """Resolved owner authority for a path-claim row.

    Exactly one of ``item_id`` / ``session_id`` / ``work_claim_id`` is
    populated, keyed by ``kind``.
    """

    kind: str
    item_id: Optional[int] = None
    session_id: Optional[str] = None
    work_claim_id: Optional[int] = None


@dataclass(frozen=True)
class Provenance:
    """Resolved registration provenance for a path-claim row."""

    actor_id: int
    session_id: Optional[str]


def validate_owner(
    owner_kind: str,
    *,
    owner_item_id: Optional[int] = None,
    owner_session_id: Optional[str] = None,
    owner_work_claim_id: Optional[int] = None,
) -> Owner:
    """Validate the typed owner contract and return a :class:`Owner`.

    Refuses unknown owner kinds and field combinations that do not
    match the typed contract (item-owned needs item id; session-owned
    needs session id; process-owned needs work-claim id; the off-axis
    fields must be NULL).
    """
    if owner_kind not in VALID_OWNER_KINDS:
        raise InvalidOwnerKind(
            f"owner_kind={owner_kind!r} not in {VALID_OWNER_KINDS!r}"
        )
    if owner_kind == OWNER_KIND_ITEM:
        if owner_item_id is None:
            raise InvalidOwnerCombination(
                "owner_kind='item' requires owner_item_id"
            )
        if owner_session_id is not None or owner_work_claim_id is not None:
            raise InvalidOwnerCombination(
                "owner_kind='item' must have owner_session_id and "
                "owner_work_claim_id NULL (use provenance fields for "
                "the registering session)"
            )
        return Owner(kind=OWNER_KIND_ITEM, item_id=int(owner_item_id))
    if owner_kind == OWNER_KIND_SESSION:
        if not owner_session_id:
            raise InvalidOwnerCombination(
                "owner_kind='session' requires owner_session_id"
            )
        if owner_item_id is not None or owner_work_claim_id is not None:
            raise InvalidOwnerCombination(
                "owner_kind='session' must have owner_item_id and "
                "owner_work_claim_id NULL"
            )
        return Owner(kind=OWNER_KIND_SESSION, session_id=str(owner_session_id))
    if owner_kind == OWNER_KIND_PROCESS:
        if owner_work_claim_id is None:
            raise InvalidOwnerCombination(
                "owner_kind='process' requires owner_work_claim_id"
            )
        if owner_item_id is not None or owner_session_id is not None:
            raise InvalidOwnerCombination(
                "owner_kind='process' must have owner_item_id and "
                "owner_session_id NULL"
            )
        return Owner(kind=OWNER_KIND_PROCESS, work_claim_id=int(owner_work_claim_id))
    raise InvalidOwnerKind(  # pragma: no cover — guarded above
        f"unhandled owner_kind={owner_kind!r}"
    )


def classify_backfill(
    *,
    item_id: Optional[int],
    work_claim_id: Optional[int],
    session_id: Optional[str],
) -> Owner:
    """Classify a legacy row by its non-typed signals.

    Used by the one-shot migration backfill and by the doctor HC to
    name the deterministic answer for a row that does not yet carry
    typed owner columns. Refuses contradictory signal sets — a row
    that carries BOTH item_id and work_claim_id is not classified;
    the caller (migration or doctor) decides whether to flag, prompt,
    or skip.
    """
    has_item = item_id is not None
    has_work_claim = work_claim_id is not None
    has_session = bool(session_id)
    if has_item and has_work_claim:
        raise ContradictoryOwnerSignals(
            "row carries both item_id and work_claim_id; cannot classify"
        )
    if has_item:
        return Owner(kind=OWNER_KIND_ITEM, item_id=int(item_id))
    if has_work_claim:
        return Owner(kind=OWNER_KIND_PROCESS, work_claim_id=int(work_claim_id))
    if has_session:
        return Owner(kind=OWNER_KIND_SESSION, session_id=str(session_id))
    raise ContradictoryOwnerSignals(
        "row has no item_id, work_claim_id, or session_id; cannot classify"
    )


def owner_from_row(row: Mapping[str, Any]) -> Optional[Owner]:
    """Extract the typed owner from a row mapping; ``None`` when un-typed.

    Reads ``owner_kind`` plus its required owner field. Returns
    ``None`` when ``owner_kind`` is missing or NULL (row not yet
    migrated). Callers that need a guaranteed answer either backfill
    via :func:`classify_backfill` or treat the absence as a typed-row
    error.
    """
    kind = row.get("owner_kind") if hasattr(row, "get") else None
    if kind is None:
        return None
    return validate_owner(
        kind,
        owner_item_id=row.get("owner_item_id"),
        owner_session_id=row.get("owner_session_id"),
        owner_work_claim_id=row.get("owner_work_claim_id"),
    )


def provenance_from_row(row: Mapping[str, Any]) -> Provenance:
    """Extract provenance fields from a row, preferring registered_by_*.

    Falls back to the legacy ``actor_id`` / ``session_id`` columns
    during cutover when ``registered_by_*`` are still NULL.
    """
    actor_id = row.get("registered_by_actor_id")
    if actor_id is None:
        actor_id = row.get("actor_id")
    session = row.get("registered_by_session_id")
    if session is None:
        session = row.get("session_id")
    return Provenance(
        actor_id=int(actor_id) if actor_id is not None else 0,
        session_id=str(session) if session else None,
    )


def derive_owner_from_signals(
    *,
    item_id: Optional[int],
    work_claim_id: Optional[int],
    session_id: Optional[str],
) -> Optional[Owner]:
    """Derive typed owner from register-time signals (priority: item > process > session).

    Returns ``None`` when no signals are present — the row is registered
    with ``owner_kind=NULL`` for legacy compatibility and surfaced by
    ``HC-path-claim-owner-kind`` at doctor time.
    """
    if item_id is not None:
        return Owner(kind=OWNER_KIND_ITEM, item_id=int(item_id))
    if work_claim_id is not None:
        return Owner(kind=OWNER_KIND_PROCESS, work_claim_id=int(work_claim_id))
    if session_id:
        return Owner(kind=OWNER_KIND_SESSION, session_id=str(session_id))
    return None


_NULL_OWNER_COLS: dict[str, Any] = {
    "owner_kind": None,
    "owner_item_id": None,
    "owner_session_id": None,
    "owner_work_claim_id": None,
}


def owner_columns_for_writer(owner: Owner) -> dict[str, Any]:
    """Return the column→value mapping for INSERT of typed owner columns.

    Writers compose this with the existing legacy column mapping so
    both the new typed columns and the legacy compatibility columns
    are populated in a single INSERT.
    """
    cols: dict[str, Any] = {
        "owner_kind": owner.kind,
        "owner_item_id": None,
        "owner_session_id": None,
        "owner_work_claim_id": None,
    }
    if owner.kind == OWNER_KIND_ITEM:
        cols["owner_item_id"] = owner.item_id
    elif owner.kind == OWNER_KIND_SESSION:
        cols["owner_session_id"] = owner.session_id
    elif owner.kind == OWNER_KIND_PROCESS:
        cols["owner_work_claim_id"] = owner.work_claim_id
    return cols


def owner_columns_or_null(owner: Optional[Owner]) -> dict[str, Any]:
    """Convenience wrapper: typed columns for ``Owner``, else NULL set."""
    if owner is None:
        return dict(_NULL_OWNER_COLS)
    return owner_columns_for_writer(owner)


__all__ = [
    "ContradictoryOwnerSignals",
    "InvalidOwnerCombination",
    "InvalidOwnerKind",
    "OWNER_KIND_ITEM",
    "OWNER_KIND_PROCESS",
    "OWNER_KIND_SESSION",
    "Owner",
    "OwnerError",
    "Provenance",
    "VALID_OWNER_KINDS",
    "classify_backfill",
    "derive_owner_from_signals",
    "owner_columns_for_writer",
    "owner_columns_or_null",
    "owner_from_row",
    "provenance_from_row",
    "validate_owner",
]
