"""Cross-ticket overlap detection for the §7.1 joint gate.

Owns the surface-signature comparator and :func:`detect_overlap` — the
public surface re-exported from
:mod:`yoke_core.domain.db_mutation_gate`.

The detector is a pure function over already-validated profiles so
unit tests can exercise it without staging a full DB.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Mapping, Optional, Set, Tuple

from yoke_core.domain.db_mutation_profile import STATE_DECLARED


def _surface_signature(surface: Mapping[str, Any]) -> Tuple[str, Optional[Tuple[str, ...]]]:
    """Return ``(table, columns_tuple_or_None)`` for an overlap comparator."""
    table = str(surface.get("table") or "")
    columns = surface.get("columns")
    if columns is None:
        return (table, None)
    return (table, tuple(sorted({str(c) for c in columns if c})))


def _surface_intersection_columns(
    a: Tuple[str, Optional[Tuple[str, ...]]],
    b: Tuple[str, Optional[Tuple[str, ...]]],
) -> Optional[Tuple[str, ...]]:
    """Return the column set shared by two surface signatures on the same table.

    Empty tuple means "shared at table grain" (one or both sides omit
    columns).  ``None`` means no intersection (different tables).
    """
    if a[0] != b[0]:
        return None
    if a[1] is None or b[1] is None:
        return ()  # table grain — covers everything
    shared = tuple(sorted(set(a[1]) & set(b[1])))
    return shared


def detect_overlap(
    candidate: Mapping[str, Any],
    others: Iterable[Mapping[str, Any]],
    *,
    dependency_pairs: Optional[Set[Tuple[int, int]]] = None,
) -> List[str]:
    """Run §7.1 step e cross-ticket overlap detection.

    Both *candidate* and *others* must be already-validated profiles.
    Profiles with ``state="none"`` are ignored on either side.

    *dependency_pairs* is an optional set of ``(min_id, max_id)`` integer
    pairs.  When the candidate ↔ other pair is present in the set, the
    overlap detector treats the pair as serializable: dependency
    ordering already enforces non-simultaneous live application, so the
    rebuild-dominance, data-kind, and schema-only overlap branches are
    skipped on shared surfaces.  Disjoint-table and disjoint-column
    cases stay unaffected.  Callers that do not pass the set get the
    pre-bypass behavior.

    Returns a list of operator-facing conflict descriptions; an empty
    list means no conflicts.  Resolution paths (dependency edge, merge,
    narrow) are not encoded here — those are operator decisions surfaced
    by the gate's error messages.
    """
    if candidate.get("state") != STATE_DECLARED:
        return []

    cand_surfaces = [
        _surface_signature(s) for s in (candidate.get("affected_surfaces") or [])
    ]
    cand_schema_kinds = set(candidate.get("schema_kinds") or [])
    cand_data_kinds = set(candidate.get("data_kinds") or [])
    cand_id = candidate.get("__item_id")  # optional caller annotation
    dep_pairs = dependency_pairs or frozenset()

    conflicts: List[str] = []

    for other in others:
        if other.get("state") != STATE_DECLARED:
            continue
        other_id = other.get("__item_id")
        if cand_id is not None and other_id == cand_id:
            continue  # never compare against self
        dependency_bypass = False
        if cand_id is not None and other_id is not None:
            try:
                pair = (
                    min(int(cand_id), int(other_id)),
                    max(int(cand_id), int(other_id)),
                )
            except (TypeError, ValueError):
                pair = None
            if pair is not None and pair in dep_pairs:
                dependency_bypass = True
        other_surfaces = [
            _surface_signature(s) for s in (other.get("affected_surfaces") or [])
        ]
        other_schema_kinds = set(other.get("schema_kinds") or [])
        other_data_kinds = set(other.get("data_kinds") or [])
        rebuild_present = (
            "rebuild" in cand_schema_kinds or "rebuild" in other_schema_kinds
        )
        for cs in cand_surfaces:
            for os_ in other_surfaces:
                shared_cols = _surface_intersection_columns(cs, os_)
                if shared_cols is None:
                    continue  # disjoint tables
                # Step 2: rebuild dominance.  Skipped when dependency-ordered.
                if rebuild_present:
                    if dependency_bypass:
                        continue
                    conflicts.append(
                        _conflict_msg(
                            other_id, cs[0], shared_cols,
                            "rebuild dominance — at least one side declares "
                            "schema_kinds:rebuild on a shared surface",
                        )
                    )
                    continue
                # Step 3: column disjointness.  Only true when BOTH sides
                # declare columns and intersection is empty.  Always applies.
                if cs[1] and os_[1] and not shared_cols:
                    continue  # disjoint columns — no conflict
                # Step 4: data-kind presence on shared surface.
                if cand_data_kinds or other_data_kinds:
                    if dependency_bypass:
                        continue
                    conflicts.append(
                        _conflict_msg(
                            other_id, cs[0], shared_cols,
                            "data-kind presence on shared surface — at "
                            "least one ticket declares a data_kind",
                        )
                    )
                    continue
                # Step 5: schema-only overlap on the same column.
                schema_overlap = (
                    {"additive", "destructive"} & cand_schema_kinds
                ) and (
                    {"additive", "destructive"} & other_schema_kinds
                )
                if schema_overlap:
                    if dependency_bypass:
                        continue
                    if shared_cols:
                        conflicts.append(
                            _conflict_msg(
                                other_id, cs[0], shared_cols,
                                "schema-only overlap on the same column(s) — "
                                "{additive, destructive} on both sides",
                            )
                        )
                    else:
                        conflicts.append(
                            _conflict_msg(
                                other_id, cs[0], shared_cols,
                                "schema-only overlap at table grain — "
                                "{additive, destructive} on both sides",
                            )
                        )

    # Deduplicate while preserving order (multiple surfaces can re-trigger
    # the same blocker against the same other ticket).
    seen: set = set()
    deduped: List[str] = []
    for msg in conflicts:
        if msg not in seen:
            seen.add(msg)
            deduped.append(msg)
    return deduped


def _conflict_msg(
    other_id: Any,
    table: str,
    columns: Tuple[str, ...],
    reason: str,
) -> str:
    other_label = f"YOK-{other_id}" if other_id is not None else "another non-terminal ticket"
    if columns:
        col_part = f" columns {sorted(columns)}"
    else:
        col_part = " (table grain)"
    return f"{other_label} conflicts on table '{table}'{col_part}: {reason}"


__all__ = [
    "_surface_intersection_columns",
    "_surface_signature",
    "detect_overlap",
]
