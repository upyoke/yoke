"""Who closed plan groups answered across each run's supersession lineage.

A presentation of several runs reads every presented run's lineage and groups
once, so the report's cost does not grow with the runs it shows.
"""

from __future__ import annotations

from typing import Any, Iterable

from yoke_core.domain.db_helpers import query_rows


def _lineages(conn: Any, runs: Iterable[str]) -> dict[str, list[str]]:
    """Each run with the runs it superseded, newest first, in one read."""
    roots = sorted({str(run) for run in runs})
    found: dict[str, list[str]] = {run: [] for run in roots}
    for row in query_rows(
        conn,
        "WITH RECURSIVE chain(root,id,supersedes_run_id,depth) AS ("
        "SELECT id,id,supersedes_run_id,0 FROM deployment_runs WHERE id=ANY(%s) "
        "UNION ALL SELECT c.root,r.id,r.supersedes_run_id,c.depth+1 "
        "FROM deployment_runs r JOIN chain c ON r.id=c.supersedes_run_id "
        "WHERE c.depth<64) SELECT root,id FROM chain ORDER BY root,depth",
        (roots,),
    ):
        found[str(row["root"])].append(str(row["id"]))
    return found


def _coverage(conn: Any, runs: Iterable[str]) -> dict[str, dict[int, set[int]]]:
    from yoke_core.domain.deployment_qa_plan_groups import run_groups

    lineages = _lineages(conn, runs)
    groups = run_groups(conn, {run for chain in lineages.values() for run in chain})
    coverage: dict[str, dict[int, set[int]]] = {}
    for root, chain in lineages.items():
        plans = coverage.setdefault(root, {})
        for group in groups:
            if group.closed and group.run_id in chain:
                plans.setdefault(group.plan_id, set()).update(
                    group.covered_item_ids or ()
                )
    return coverage


def lineage_coverage(conn: Any, run_id: str) -> dict[int, set[int]]:
    """Each plan's members closed groups answered in this run or its predecessors."""
    from yoke_core.domain.deployment_qa_presentation_facts import presented_run_ids
    from yoke_core.domain.deployment_qa_presentation_reads import presentation_read

    runs = presented_run_ids(conn, str(run_id))
    if runs:
        return presentation_read(
            conn, ("closed_group_coverage", runs), lambda: _coverage(conn, runs)
        ).get(str(run_id), {})
    return presentation_read(
        conn,
        ("closed_group_coverage", str(run_id)),
        lambda: _coverage(conn, [str(run_id)]).get(str(run_id), {}),
    )


__all__ = ["lineage_coverage"]
