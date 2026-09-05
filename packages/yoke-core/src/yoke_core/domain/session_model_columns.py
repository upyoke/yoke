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
duplicate-registration healing, reactivation, and the launch binding that
stamps a launched session's ask cannot drift apart. That last writer is
why the gap-filling half matters as much as the never-rewriting half: a
session whose harness could not tell it which model it was asked for
registers with the requested columns empty, and the launch record fills
them without touching a session that answered for itself.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from yoke_contracts.session_control.model_selection import (
    LaunchModelSelection,
    SURFACE_CONTEXT_WINDOWS,
    SURFACE_EFFORT_LEVELS,
    resume_selection_mode,
)
from yoke_contracts.session_model_facts import (
    MODEL_FACT_FIELDS as MODEL_COLUMNS,
    REQUESTED_FIELDS as REQUESTED_COLUMNS,
    SERVED_FIELDS as SERVED_COLUMNS,
    SessionModelFacts,
)
from yoke_core.domain.session_relay_storage import marker


def facts_values(facts: SessionModelFacts) -> List[Any]:
    """Return the values for :data:`MODEL_COLUMNS`, in that order."""
    return [getattr(facts, column) for column in MODEL_COLUMNS]


def stored_facts(row: Any) -> SessionModelFacts:
    """Read the model facts a ``harness_sessions`` row already holds."""
    return SessionModelFacts(
        **{column: _value(row, column) for column in MODEL_COLUMNS}
    )


def _replaces_served_model(stored: Optional[str], incoming: Optional[str]) -> bool:
    """True when ``incoming`` is a newer reading rather than a vaguer one.

    A composed variant name contains the bare family id it belongs to
    (``cursor-grok-4.6-xhigh`` contains ``grok-4.6``), so a name the stored
    one already contains is the same model reported less precisely — an
    older client's payload self-report, not a later measurement. Two
    unrelated names are both measurements and the later one wins, which is
    how a mid-run model switch heals.
    """
    if incoming is None:
        return False
    if stored is None:
        return True
    return incoming not in stored


def merged_facts(existing: Any, incoming: SessionModelFacts) -> SessionModelFacts:
    """Fold an incoming reading into a stored row under both write rules."""
    stored = stored_facts(existing)
    merged = {}
    for column in SERVED_COLUMNS:
        if column == "model" and not _replaces_served_model(
            stored.model, incoming.model
        ):
            merged[column] = stored.model
            continue
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


def resume_selection_for_facts(
    surface: str, facts: SessionModelFacts
) -> LaunchModelSelection:
    """Return only the session selection a native resume must re-send.

    An attestation is current-session truth, including its omissions. Once
    any served fact exists, the original launch request is therefore never
    mixed back in. Unsupported knobs remain absent instead of being replaced
    with a machine preference.
    """
    if resume_selection_mode(surface) != "explicit":
        return LaunchModelSelection()
    if facts.attested():
        model = facts.model
        effort = facts.reasoning_effort
        context = facts.context_window_tokens
    else:
        model = facts.requested_model
        effort = facts.requested_reasoning_effort
        context = facts.requested_context_window_tokens
    normalized_model = str(model or "").strip() or None
    normalized_effort = str(effort or "").strip().lower() or None
    if normalized_effort not in SURFACE_EFFORT_LEVELS.get(surface, ()):
        normalized_effort = None
    if context not in SURFACE_CONTEXT_WINDOWS.get(surface, ()):
        context = None
    if surface == "cursor-cli" and normalized_model is None:
        normalized_effort = None
        context = None
    return LaunchModelSelection(normalized_model, normalized_effort, context)


def resume_model_selection(
    conn: Any, *, session_id: str, surface: str
) -> LaunchModelSelection:
    """Read one target session and resolve its native-resume selection."""
    if resume_selection_mode(surface) != "explicit":
        return LaunchModelSelection()
    p = marker(conn)
    row = conn.execute(
        "SELECT model,reasoning_effort,context_window_tokens,"
        "requested_model,requested_reasoning_effort,"
        "requested_context_window_tokens FROM harness_sessions "
        f"WHERE session_id={p}",
        (session_id,),
    ).fetchone()
    if row is None:
        return LaunchModelSelection()
    facts = SessionModelFacts(
        model=row[0],
        reasoning_effort=row[1],
        context_window_tokens=row[2],
        requested_model=row[3],
        requested_reasoning_effort=row[4],
        requested_context_window_tokens=row[5],
    )
    return resume_selection_for_facts(surface, facts)


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
    "resume_model_selection",
    "resume_selection_for_facts",
    "stored_facts",
]
