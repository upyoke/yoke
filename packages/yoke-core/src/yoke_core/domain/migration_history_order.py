"""Declared precedence: an entry that must run before an earlier-numbered one.

Ordinals order the history, and new entries always take the next ordinal, so
an entry that has to run *before* an already-published one cannot be numbered
into place. It declares the dependency instead::

    PRECEDES = ("0053_retire_advance_skill",)

The declaration matters only to a database that owes both entries: there the
declaring entry runs immediately before the earliest entry it names. A
database that already applied the named entry owes only the declarer, and
membership -- not order -- decides that.

Only :func:`yoke_core.domain.migration_history.ordered_entries` applies the
declaration, so boot, rehearsal, fleet preflight, and readiness share one
order. Ordinal views (duplicate detection, merge-time history extension) stay
purely numeric: a declaration never changes which number an entry takes.

The declaration is read from source with ``ast``, never by importing the
module, because ordering a history must not execute any entry.
"""

from __future__ import annotations

import ast
from typing import Dict, Iterable, List, Tuple

from yoke_core.domain.migration_history import HistoryError, MigrationEntry

PRECEDES_NAME = "PRECEDES"


def declared_precedence(entry: MigrationEntry) -> Tuple[str, ...]:
    """The entry names *entry* declares it must precede, or ``()``."""
    tree = ast.parse(entry.path.read_bytes(), filename=str(entry.path))
    for node in tree.body:
        if not (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == PRECEDES_NAME
                for target in node.targets
            )
        ):
            continue
        value = node.value
        if not (
            isinstance(value, ast.Tuple)
            and value.elts
            and all(
                isinstance(element, ast.Constant) and isinstance(element.value, str)
                for element in value.elts
            )
        ):
            raise HistoryError(
                f"{entry.name}: {PRECEDES_NAME} must be a non-empty literal tuple "
                'of entry names, e.g. PRECEDES = ("0053_retire_advance_skill",)'
            )
        return tuple(element.value for element in value.elts)
    return ()


def _validated(
    entries: Iterable[MigrationEntry],
) -> Dict[str, Tuple[str, ...]]:
    by_name = {entry.name: entry for entry in entries}
    declared: Dict[str, Tuple[str, ...]] = {}
    for entry in by_name.values():
        targets = declared_precedence(entry)
        if not targets:
            continue
        for target in targets:
            known = by_name.get(target)
            if known is None:
                raise HistoryError(
                    f"{entry.name}: {PRECEDES_NAME} names {target!r}, which is "
                    "not an entry in this history; name an existing entry stem"
                )
            # Requiring a lower ordinal is also what makes cycles impossible:
            # every edge points strictly down the numbering.
            if known.sequence >= entry.sequence:
                raise HistoryError(
                    f"{entry.name}: {PRECEDES_NAME} names {target!r}, which does "
                    "not have a lower ordinal; an entry can only be declared to "
                    "run before an earlier-numbered one"
                )
        declared[entry.name] = targets
    return declared


def apply_declared_precedence(
    entries: Tuple[MigrationEntry, ...],
) -> Tuple[MigrationEntry, ...]:
    """Reorder ordinal-sorted *entries* so each declarer runs before its targets.

    Declarers are placed in ascending ordinal, each immediately before the
    earliest-positioned entry it names. Because targets always carry lower
    ordinals, a target that is itself a declarer is already placed, so chains
    resolve in one pass.
    """
    declared = _validated(entries)
    if not declared:
        return entries
    ordered: List[MigrationEntry] = [
        entry for entry in entries if entry.name not in declared
    ]
    for entry in entries:
        targets = declared.get(entry.name)
        if targets is None:
            continue
        positions = [
            index for index, placed in enumerate(ordered) if placed.name in targets
        ]
        ordered.insert(min(positions), entry)
    return tuple(ordered)


__all__ = [
    "PRECEDES_NAME",
    "apply_declared_precedence",
    "declared_precedence",
]
