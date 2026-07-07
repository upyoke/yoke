"""STRATEGIZE/FEED process-claim boundary shared by the strategy handlers.

The registry claim-verification matrix models item/epic claim kinds,
not process claims, so the strategy write handlers enforce their
boundary here (the ``claims_work_release_session_scoped`` precedent).
The conflict group is per-project (``strategy-control-plane:<slug>``),
keyed on the project whose docs the request targets:

- ``strategy.doc.replace`` requires the calling session to HOLD an
  active claim in that project's strategy control-plane conflict group
  (:func:`session_holds_strategy_claim`).
- ``strategy.ingest.run`` requires that no OTHER session holds it
  (:func:`foreign_strategy_claim_holder`) — the editor bridge never
  needs a lock of its own, but must not race a live strategize/feed
  session's write window on the same project.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.work_processes import (
    PROCESS_STRATEGIZE,
    conflict_group_for,
)

CLAIM_ACQUIRE_RECIPE = (
    "yoke claims work acquire --process STRATEGIZE --reason <why>"
)


def session_holds_strategy_claim(
    conn: Any, session_id: str, project_slug: str,
) -> bool:
    """True when the session holds the project's live STRATEGIZE/FEED claim."""
    group = conflict_group_for(PROCESS_STRATEGIZE, project_slug)
    row = conn.execute(
        "SELECT COUNT(*) FROM work_claims "
        "WHERE session_id = %s AND target_kind = 'process' "
        "AND conflict_group = %s AND released_at IS NULL",
        (session_id, group),
    ).fetchone()
    return bool(row and int(row[0]) > 0)


def foreign_strategy_claim_holder(
    conn: Any, session_id: str, project_slug: str,
) -> Optional[str]:
    """Return another session's id when it holds the project's live claim.

    The ingest editor bridge bounces off a *foreign* live STRATEGIZE/FEED
    claim (a strategize/feed session owns that project's write window)
    but never requires one of its own — the claim holder itself may use
    either write path. Passing an empty ``session_id`` models direct
    terminal calls, where any live process claim is foreign.
    """
    group = conflict_group_for(PROCESS_STRATEGIZE, project_slug)
    row = conn.execute(
        "SELECT session_id FROM work_claims "
        "WHERE session_id <> %s AND target_kind = 'process' "
        "AND conflict_group = %s AND released_at IS NULL "
        "ORDER BY claimed_at DESC LIMIT 1",
        (session_id, group),
    ).fetchone()
    if row is None:
        return None
    return str(row["session_id"] if hasattr(row, "keys") else row[0])


__all__ = [
    "CLAIM_ACQUIRE_RECIPE",
    "foreign_strategy_claim_holder",
    "session_holds_strategy_claim",
]
