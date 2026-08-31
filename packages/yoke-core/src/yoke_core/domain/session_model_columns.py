"""How the two kinds of session model fact are written and healed.

``harness_sessions`` keeps the ask and the served truth in separate
columns, and they follow opposite write rules:

* **Served** (``model``, ``reasoning_effort``, ``context_window_tokens``)
  is per-turn truth. A provider attestation always replaces what is
  stored, because a session that switched model or effort mid-run is
  currently serving the later value. Having nothing to attest never
  overwrites what an earlier read proved.
* **Requested** (``requested_model``, ``requested_reasoning_effort``,
  ``requested_context_window_tokens``) is stamped once. The ask was fixed
  when the session was launched, so a later re-registration fills a gap
  but never rewrites an answer.

Both rules are here rather than in the registrar so that insert,
duplicate-registration healing, and reactivation cannot drift apart.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from yoke_contracts.session_model_facts import (
    MODEL_FACT_FIELDS as MODEL_COLUMNS,
    REQUESTED_FIELDS as REQUESTED_COLUMNS,
    SERVED_FIELDS as SERVED_COLUMNS,
    SessionModelFacts,
)


def facts_values(facts: SessionModelFacts) -> List[Any]:
    """Return the values for :data:`MODEL_COLUMNS`, in that order."""
    return [getattr(facts, column) for column in MODEL_COLUMNS]


def stored_facts(row: Any) -> SessionModelFacts:
    """Read the model facts a ``harness_sessions`` row already holds."""
    return SessionModelFacts(**{column: _value(row, column) for column in MODEL_COLUMNS})


def merged_facts(existing: Any, incoming: SessionModelFacts) -> SessionModelFacts:
    """Fold an incoming reading into a stored row under both write rules."""
    stored = stored_facts(existing)
    merged = {}
    for column in SERVED_COLUMNS:
        merged[column] = getattr(incoming, column) or getattr(stored, column)
    for column in REQUESTED_COLUMNS:
        merged[column] = getattr(stored, column) or getattr(incoming, column)
    return SessionModelFacts(**merged)


def changed_columns(
    existing: Any, incoming: SessionModelFacts
) -> Tuple[List[str], List[Any]]:
    """Return the columns whose stored value the merge would change.

    An empty result is the settled case — the row already says everything
    this reading knows — and lets callers skip the write entirely.
    """
    stored = stored_facts(existing)
    merged = merged_facts(existing, incoming)
    columns: List[str] = []
    values: List[Any] = []
    for column in MODEL_COLUMNS:
        value = getattr(merged, column)
        if value != getattr(stored, column):
            columns.append(column)
            values.append(value)
    return columns, values


def _value(row: Any, column: str) -> Optional[Any]:
    if row is None:
        return None
    try:
        return row[column] or None
    except (KeyError, IndexError, TypeError):
        return None


__all__ = [
    "MODEL_COLUMNS",
    "REQUESTED_COLUMNS",
    "SERVED_COLUMNS",
    "changed_columns",
    "facts_values",
    "merged_facts",
    "stored_facts",
]
