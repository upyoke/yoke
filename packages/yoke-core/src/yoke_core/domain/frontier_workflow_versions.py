"""The workflow definitions a frontier scan needs, read once per scan.

Every item pins an immutable workflow version, and the scan needs that
version's stage vocabulary to classify the item. Joining the definition onto
each item row makes the scan carry one copy of the definition per item — on a
board with thousands of items and a couple dozen versions that is the same
bytes hundreds of times over, decoded and digest-verified once per copy.

The definitions are read here instead: one statement, one decode and one
digest check per version. Reading them first also lets the item scan skip the
statuses it would only discard. :func:`skipped_statuses` names, per version,
exactly the statuses ``frontier_classify.classify_next_action`` maps to
``SKIP`` plus the ``failed`` stage the scan drops right after — and nothing
else, so a status the definition does not recognize still reaches the
classifier and still raises rather than vanishing from the board.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Tuple

from .workflow_runtime import (
    ENGINE_TERMINAL_STAGE_IDS,
    WorkflowRuntime,
    load_workflow_runtime,
    workflow_runtime_from_row,
)

#: Stages the scan discards regardless of which definition pins them:
#: the engine's own terminal stages plus ``failed``, which
#: ``compute_frontier`` drops as an exceptional-list concern.
ENGINE_SKIPPED_STATUSES: FrozenSet[str] = ENGINE_TERMINAL_STAGE_IDS | {"failed"}

_VERSIONS_SQL = """
SELECT v.id AS workflow_version_id, v.workflow_id, v.version,
       v.definition_json, v.definition_digest
FROM workflow_versions v
"""


def skipped_statuses(runtime: WorkflowRuntime) -> FrozenSet[str]:
    """Return the statuses a frontier scan discards for this version."""
    return frozenset(runtime.terminal_stage_ids) | ENGINE_SKIPPED_STATUSES


@dataclass(frozen=True)
class FrontierWorkflowVersions:
    """Every published workflow version, decoded once."""

    runtimes: Dict[int, WorkflowRuntime]

    def runtime_for(self, conn: Any, row: Dict[str, Any]) -> WorkflowRuntime:
        """Return the decoded runtime pinned by one scanned item row.

        A version published between the definition read and the item read is
        absent from the batch; it is read on its own and kept, so the scan
        never fails on a row the item query legitimately returned.
        """
        version_id = int(row["workflow_version_id"])
        runtime = self.runtimes.get(version_id)
        if runtime is None:
            runtime = load_workflow_runtime(
                conn,
                workflow_id=str(row["workflow_id"]),
                workflow_version_id=version_id,
            )
            self.runtimes[version_id] = runtime
        return runtime

    def skip_clause(self, marker: str) -> Tuple[str, List[Any]]:
        """Render the ``AND NOT (...)`` clause excluding discarded statuses.

        Versions sharing a skip set share one clause, so the rendered SQL
        stays short even on a project with many published versions.
        """
        groups: Dict[FrozenSet[str], List[int]] = {}
        for version_id, runtime in self.runtimes.items():
            groups.setdefault(skipped_statuses(runtime), []).append(version_id)

        fragments: List[str] = []
        params: List[Any] = []
        for statuses, version_ids in groups.items():
            version_ids = sorted(version_ids)
            ordered_statuses = sorted(statuses)
            version_marks = ", ".join(marker for _ in version_ids)
            status_marks = ", ".join(marker for _ in ordered_statuses)
            fragments.append(
                f" AND NOT (i.workflow_version_id IN ({version_marks})"
                f" AND i.status IN ({status_marks}))"
            )
            params.extend(version_ids)
            params.extend(ordered_statuses)
        return "".join(fragments), params


def load_frontier_workflow_versions(conn: Any) -> FrontierWorkflowVersions:
    """Read and decode every published workflow version in one statement."""
    cursor = conn.cursor()
    cursor.execute(_VERSIONS_SQL)
    rows = cursor.fetchall()
    col_names = [desc[0] for desc in cursor.description]
    runtimes: Dict[int, WorkflowRuntime] = {}
    for row in rows:
        values = dict(zip(col_names, row))
        runtimes[int(values["workflow_version_id"])] = workflow_runtime_from_row(values)
    return FrontierWorkflowVersions(runtimes=runtimes)


__all__ = [
    "ENGINE_SKIPPED_STATUSES",
    "FrontierWorkflowVersions",
    "load_frontier_workflow_versions",
    "skipped_statuses",
]
