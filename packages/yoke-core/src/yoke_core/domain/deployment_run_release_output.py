"""Commits a release wrote itself, and which run's automation wrote them.

A release does not only ship commits — it writes some. When a run's promotion
materializes a version pin onto a project's trunk, that push is release
output: a real commit that no backlog item authored, landing in the very
range the next release's composition validation reads. Attribution has
nothing to find there, so every following release refuses the same commit
until somebody records a ``composition_resolution`` by hand, and a waiver
that routine stops meaning anything.

So the run that produced the commit says so, and attribution reads that
record instead of guessing from an author name or a file path, either of
which anyone able to push can wear. The record lives beside the commits the
run pinned, inside ``bound_sources``, because both answer the same question
about the same project: which source did this release involve.

This module is the reading half, which carried-work derivation consults only
for a commit no item claimed — the item always wins, and a recorded claim
only ever explains what attribution had already given up on. The guarded
write that produces the record is
:mod:`yoke_core.domain.deployment_run_release_output_record`.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.deployment_run_bound_sources import (
    BOUND_SOURCES_FIELD,
    bound_sources_recorded,
    parse_bound_sources,
)


#: Where one project's produced commits sit inside its ``bound_sources`` entry.
RELEASE_OUTPUT_KEY = "outputs"

#: What a promotion that rewrote a version pin calls its own commit.
REASON_RELEASE_PIN = "release_pin_materialization"


def _cell(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def project_release_outputs(
    payload: Mapping[str, Any],
) -> dict[int, tuple[dict[str, str], ...]]:
    """Every commit one stored record says its run produced, by project id."""
    outputs: dict[int, tuple[dict[str, str], ...]] = {}
    for entry in payload.get("projects") or []:
        if not isinstance(entry, Mapping):
            continue
        project_id = entry.get("project_id")
        if project_id is None:
            continue
        recorded = tuple(
            {
                "commit_sha": str(output.get("commit_sha") or "").strip().lower(),
                "reason": str(output.get("reason") or ""),
            }
            for output in entry.get(RELEASE_OUTPUT_KEY) or []
            if isinstance(output, Mapping)
            and str(output.get("commit_sha") or "").strip()
        )
        if recorded:
            outputs[int(project_id)] = recorded
    return outputs


def release_output_runs(conn: Any, project_id: int) -> dict[str, dict[str, str]]:
    """Commit sha to the run that recorded producing it, for one project.

    Keyed by commit rather than by run because the caller holds a range and
    asks about each commit in it. The earliest recording run wins a repeated
    claim, so a retry that inherited its predecessor's record still credits
    the release that actually wrote the commit.
    """
    if not bound_sources_recorded(conn):
        return {}
    rows = conn.execute(
        f"SELECT id,COALESCE({BOUND_SOURCES_FIELD},'') AS {BOUND_SOURCES_FIELD} "
        "FROM deployment_runs "
        f"WHERE COALESCE({BOUND_SOURCES_FIELD},'')<>'' "
        "ORDER BY created_at,id"
    ).fetchall()
    produced: dict[str, dict[str, str]] = {}
    for row in rows:
        run = str(_cell(row, "id", 0) or "")
        payload = parse_bound_sources(_cell(row, BOUND_SOURCES_FIELD, 1))
        for output in project_release_outputs(payload).get(int(project_id), ()):
            produced.setdefault(
                output["commit_sha"],
                {"run_id": run, "reason": output["reason"]},
            )
    return produced


__all__ = [
    "REASON_RELEASE_PIN",
    "RELEASE_OUTPUT_KEY",
    "project_release_outputs",
    "release_output_runs",
]
