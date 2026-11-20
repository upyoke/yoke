"""Whether a requirement's latest non-pass attempt still answers its current target.

A superseding deployment run rebinds the obligations it carries to its own
target. A pass recorded against the old target proves the new one only
through :mod:`qa_requirement_pass_currency`; a fail (or any other non-pass)
recorded against the old target proves nothing about the new one either.
Such an attempt is stale: the requirement grades as not yet run, so the
driver captures it again instead of waiting on a decision.

An attempt or requirement with no recorded digest keeps its verdict; only a
recorded digest that differs from the live one is stale.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_requirement_pass_currency import (
    recorded_execution_target_digest,
)
from yoke_core.domain.schema_common import _column_exists


def stale_target_requirements(
    conn: Any, attempts: Mapping[int, Mapping[str, Any]]
) -> set[int]:
    """Requirement ids whose latest non-pass attempt answered another target.

    ``attempts`` maps requirement id to its selected latest attempt (any row
    with ``id`` and ``verdict``). One read fetches the live digests and the
    recorded ones for the non-pass attempts only.
    """
    candidates = {
        int(run["id"]): int(requirement_id)
        for requirement_id, run in attempts.items()
        if str(run.get("verdict") or "") != "pass"
    }
    if not candidates or not _column_exists(
        conn, "qa_requirements", "execution_target_digest"
    ):
        return set()
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = query_rows(
        conn,
        "SELECT run.id AS run_id, run.raw_result, r.execution_target_digest "
        "FROM qa_runs run JOIN qa_requirements r ON r.id=run.qa_requirement_id "
        f"WHERE run.id IN ({','.join(marker for _ in candidates)})",
        tuple(candidates),
    )
    stale = set()
    for row in rows:
        live = str(row["execution_target_digest"] or "")
        recorded = recorded_execution_target_digest(row["raw_result"])
        if live and recorded and recorded != live:
            stale.add(candidates[int(row["run_id"])])
    return stale


def current_target_attempts(
    conn: Any, attempts: Mapping[int, Mapping[str, Any]]
) -> dict[int, Mapping[str, Any]]:
    """The attempts that still grade their requirement; stale ones are unrun."""
    stale = stale_target_requirements(conn, attempts)
    return {
        int(requirement_id): run
        for requirement_id, run in attempts.items()
        if int(requirement_id) not in stale
    }


__all__ = ["current_target_attempts", "stale_target_requirements"]
