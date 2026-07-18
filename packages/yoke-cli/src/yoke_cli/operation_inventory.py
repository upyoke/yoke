"""Canonical operation tracker for Yoke-owned agent surfaces.

Single source of truth for per-operation classification across every
Yoke-owned shell surface an agent might invoke. Consumed by:

* ``verify_skill_recipes.py`` smoke harness — multi-module recipe
  accepted iff matching entry is ``status="permanent"`` or
  ``status="pending"``.
* Deny-mode contract lint — denies multi-module recipes for
  ``status="wrapped"`` entries; allows the other two classes.
* Skill body label authoring — emits the present-state label
  adjacent to each fallback recipe.
* Doctor HC ``HC-fallback-registry-coherence`` —
  verifies every ``status="wrapped"`` row has both a function-registry
  entry AND a CLI-registry adapter; verifies every ``status="pending"``
  row's ``shell_form`` parses as a valid Yoke-owned invocation.

Vocabulary discipline: present-state labels and reasons only. No
plan-doc taxonomy leaks into the enum values, status / reason strings,
or lint denial messages.

When the Atlas policy model owns surface disposition, the tracker is
absorbed — either read by that policy model as input, or migrated under
``axes.surface.disposition`` at family granularity. Until then, this
module is the canonical surface for fallback classification.

Data rows live in the sibling module
:mod:`yoke_cli.operation_inventory_data` to keep this file under the
authored-file line cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from yoke_cli.operation_inventory_data import (
    PENDING,
    PENDING_ROWS,
    PERMANENT,
    PERMANENT_ROWS,
    REASON_NO_HANDLER_REGISTERED,
    REASON_OPERATOR_BREAK_GLASS,
    REASON_TOOL_SHAPED,
    REASON_WRAPPED_BY_YOKE_CLI,
    WRAPPED,
    WRAPPED_ROWS,
)


REASON_LOW_VOLUME_OPERATOR_DEBUG = "low_volume_operator_debug"


_VALID_STATUSES: Tuple[str, ...] = (WRAPPED, PERMANENT, PENDING)
_VALID_REASONS: Tuple[str, ...] = (
    REASON_WRAPPED_BY_YOKE_CLI,
    REASON_OPERATOR_BREAK_GLASS,
    REASON_TOOL_SHAPED,
    REASON_LOW_VOLUME_OPERATOR_DEBUG,
    REASON_NO_HANDLER_REGISTERED,
)


@dataclass(frozen=True)
class OperationEntry:
    """One row per Yoke-owned shell-callable operation.

    Attributes:
        shell_form: Canonical multi-module invocation string. The
            multi-module form is always meaningful — wrapped entries
            still document the operator/debug fallback shape.
        family: Dotted family path (e.g. ``workflow_item.epic_task.review``).
        status: One of ``wrapped`` | ``permanent`` | ``pending``.
        reason: One of the closed-reason enum values above.
        proposed_function_id: Dotted function-id for ``status="pending"``
            rows (the handler-registration roster); ``None`` otherwise.
    """

    shell_form: str
    family: str
    status: str
    reason: str
    proposed_function_id: Optional[str] = None
    source_owner: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status not in _VALID_STATUSES:
            raise ValueError(
                f"OperationEntry.status must be one of {_VALID_STATUSES}; "
                f"got {self.status!r}"
            )
        if self.reason not in _VALID_REASONS:
            raise ValueError(
                f"OperationEntry.reason must be one of {_VALID_REASONS}; "
                f"got {self.reason!r}"
            )
        if self.status == PENDING and not self.proposed_function_id:
            raise ValueError(
                "OperationEntry status='pending' requires "
                f"proposed_function_id (shell_form={self.shell_form!r})"
            )
        if self.status in (WRAPPED, PERMANENT) and self.proposed_function_id:
            raise ValueError(
                f"OperationEntry status={self.status!r} must not carry "
                f"proposed_function_id (shell_form={self.shell_form!r})"
            )


def _to_entry(row) -> OperationEntry:
    return OperationEntry(
        shell_form=row.shell_form,
        family=row.family,
        status=row.status,
        reason=row.reason,
        proposed_function_id=row.proposed_function_id,
        source_owner=row.source_owner,
    )


_ALL_ENTRIES: Tuple[OperationEntry, ...] = tuple(
    _to_entry(row) for row in (*WRAPPED_ROWS, *PERMANENT_ROWS, *PENDING_ROWS)
)


def all_entries() -> Tuple[OperationEntry, ...]:
    """Return every tracker entry in canonical order (wrapped, permanent, pending)."""
    return _ALL_ENTRIES


def by_shell_form() -> Dict[str, OperationEntry]:
    """Return a dict keyed by ``shell_form`` for O(1) lookup."""
    return {entry.shell_form: entry for entry in _ALL_ENTRIES}


def by_status(status: str) -> List[OperationEntry]:
    """Return every entry matching ``status``."""
    if status not in _VALID_STATUSES:
        raise ValueError(
            f"status must be one of {_VALID_STATUSES}; got {status!r}"
        )
    return [e for e in _ALL_ENTRIES if e.status == status]


def lookup(shell_form: str) -> Optional[OperationEntry]:
    """Return the entry matching ``shell_form`` exactly, or ``None``."""
    for entry in _ALL_ENTRIES:
        if entry.shell_form == shell_form:
            return entry
    return None


def is_wrapped(shell_form: str) -> bool:
    """Return True iff ``shell_form`` matches a wrapped entry."""
    entry = lookup(shell_form)
    return entry is not None and entry.status == WRAPPED


__all__ = [
    "OperationEntry",
    "WRAPPED", "PERMANENT", "PENDING",
    "REASON_WRAPPED_BY_YOKE_CLI", "REASON_OPERATOR_BREAK_GLASS",
    "REASON_TOOL_SHAPED", "REASON_LOW_VOLUME_OPERATOR_DEBUG",
    "REASON_NO_HANDLER_REGISTERED",
    "all_entries", "by_shell_form", "by_status", "lookup", "is_wrapped",
]
