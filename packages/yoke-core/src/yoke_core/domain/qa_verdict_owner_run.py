"""Which release a carried check's result was recorded in.

A takeover moves an open requirement onto its successor run, carrying the
latest attempt with it. That attempt's result belongs to the run that was
live when it was recorded, not to the run now showing it. A row whose
attempt predates its run gains ``verdict_run_id``: the newest ancestor on
the run's ``supersedes_run_id`` chain created before the attempt.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import query_rows


def label_verdict_owner_runs(conn: Any, rows: list[dict]) -> list[dict]:
    """Set ``verdict_run_id`` on rows whose attempt an earlier run recorded."""
    runs = sorted(
        {str(row["deployment_run_id"]) for row in rows
         if row["deployment_run_id"] and row["run_id"] is not None}
    )
    chains: dict[str, list[tuple[Any, str]]] = {}
    for link in runs and query_rows(
        conn,
        # One read of every named run and its whole ancestor chain.
        "WITH RECURSIVE chain(owner,id,supersedes_run_id,created_at,depth) AS ("
        "SELECT id,id,supersedes_run_id,created_at,0 FROM deployment_runs "
        "WHERE id=ANY(%s) UNION ALL "
        "SELECT c.owner,p.id,p.supersedes_run_id,p.created_at,c.depth+1 "
        "FROM deployment_runs p JOIN chain c ON p.id=c.supersedes_run_id "
        "WHERE c.depth<64) "
        "SELECT owner,id,created_at FROM chain ORDER BY owner,depth",
        (runs,),
    ):
        chains.setdefault(str(link["owner"]), []).append(
            (link["created_at"], str(link["id"]))
        )
    for row in rows:
        row["verdict_run_id"] = None
        chain = chains.get(str(row["deployment_run_id"] or ""))
        recorded = row["happened_at"]
        if not chain or row["run_id"] is None or recorded is None:
            continue
        if recorded >= chain[0][0]:
            continue
        row["verdict_run_id"] = next(
            (run for created, run in chain[1:] if created <= recorded),
            chain[-1][1] if len(chain) > 1 else None,
        )
    return rows


__all__ = ["label_verdict_owner_runs"]
