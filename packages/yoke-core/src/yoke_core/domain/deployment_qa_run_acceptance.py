"""Whether one item's scoped QA obligations in a deployment run are accepted.

The pipeline will not advance past a QA stage whose subjects are not
accepted, so a run that reached ``succeeded`` normally satisfied every
one of them on the way through. "Normally" is the whole reason this
reader exists: an acceptance can be rejected by a human after the run
finished, a replacement producer receipt can retarget a stage so the
earlier acceptance no longer answers for it, and an operator can carry
an item toward done on evidence rather than on a live pipeline pass
(``--skip-deploy``, a resume, a run left at an unexpected status). In
each of those the run still reads ``succeeded`` while the item's own
release QA does not hold.

Scope is the item being closed, not the whole batch: its own
item-scoped stages plus every run-scoped stage, which is exactly the
set of stage verdicts that answer for this item. Another member's
outstanding item-scoped QA is that member's gate, and blocking on it
would deadlock a batch whose members legitimately finish at different
times.

Legacy flows carry no scoped QA vocabulary at all; for them this reader
returns nothing and the legacy ``deployment_run_qa`` projection stays
the only QA authority. Anything it cannot evaluate blocks with the
reason it failed on, because an unreadable release gate is not a
passing one.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_flow_policy import (
    QA_STEP_RUNNER,
    RELEASE_POLICY_SCHEMA_VERSION,
    STAGE_KIND_QA,
)
from yoke_core.domain.deployment_qa_stage_acceptance import stage_acceptance_blockers
from yoke_core.domain.deployment_qa_stage_contract import (
    DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
    deployment_qa_stage_subject,
)
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists


#: Every storage surface the scoped QA vocabulary is expressed in. A
#: universe missing any of them cannot hold a scoped obligation at all,
#: which is a different answer from a read that failed.
_SCOPED_QA_SURFACES = (
    ("deployment_flows", "definition_schema_version"),
    ("deployment_runs", "flow"),
    ("qa_requirements", "deployment_run_id"),
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _scoped_qa_storage_present(conn: Any) -> bool:
    """Whether this universe can express a scoped QA obligation at all.

    Checked explicitly rather than by swallowing a query error, so a
    transient read failure still blocks while a schema that genuinely
    predates the scoped vocabulary reports "nothing owed" instead of
    "could not tell".
    """
    return all(
        _table_exists(conn, table) and _column_exists(conn, table, column)
        for table, column in _SCOPED_QA_SURFACES
    )


def _pinned_qa_stages(conn: Any, run_id: str) -> list[dict[str, Any]]:
    """The run's own pinned QA stages, or ``[]`` for a legacy definition."""
    if not _scoped_qa_storage_present(conn):
        return []
    marker = _p(conn)
    row = conn.execute(
        "SELECT df.definition_schema_version, df.stages FROM deployment_runs dr "
        "JOIN deployment_flows df ON df.id=dr.flow "
        f"WHERE dr.id={marker}",
        (str(run_id),),
    ).fetchone()
    if row is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    schema_version = (
        row["definition_schema_version"] if hasattr(row, "keys") else row[0]
    )
    raw_stages = row["stages"] if hasattr(row, "keys") else row[1]
    if int(schema_version or 1) != RELEASE_POLICY_SCHEMA_VERSION:
        return []
    try:
        stages = json.loads(str(raw_stages))
    except (TypeError, ValueError) as exc:
        raise ValueError("deployment flow stages are invalid JSON") from exc
    return [
        dict(stage)
        for stage in stages
        if isinstance(stage, Mapping)
        and (
            stage.get("stage_kind") == STAGE_KIND_QA
            or stage.get("step_runner") == QA_STEP_RUNNER
        )
    ]


@dataclass(frozen=True)
class ItemReleaseQa:
    """One item's scoped QA standing inside one run.

    ``scoped`` is the fact a bare blocker list cannot carry: a legacy
    definition owes nothing because it has no scoped QA vocabulary at all,
    which is a different answer from every obligation being accepted, and a
    reader that showed both as "clear" would report QA on a release that
    never ran any.
    """

    scoped: bool
    blockers: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return self.scoped and not self.blockers


def item_release_qa(conn: Any, *, run_id: str, item_id: int) -> ItemReleaseQa:
    """This item's scoped QA standing in the run, as it already stands."""
    stages = _pinned_qa_stages(conn, str(run_id))
    return ItemReleaseQa(
        scoped=bool(stages),
        blockers=tuple(_stage_blockers(conn, str(run_id), int(item_id), stages)),
    )


def item_qa_acceptance_blockers(conn: Any, *, run_id: str, item_id: int) -> list[str]:
    """Every unsatisfied scoped QA verdict this item still owes in the run."""
    return list(
        item_release_qa(conn, run_id=str(run_id), item_id=int(item_id)).blockers
    )


def _stage_blockers(
    conn: Any, run_id: str, item_id: int, stages: list[dict[str, Any]]
) -> list[str]:
    blockers: list[str] = []
    for stage in stages:
        stage_name = str(stage.get("name") or "")
        item_scoped = stage.get("scope") == "item"
        member_item_id = int(item_id) if item_scoped else None
        label = f"stage {stage_name!r}"
        try:
            subject = deployment_qa_stage_subject(
                conn,
                run_id=str(run_id),
                stage_name=stage_name,
                member_item_id=member_item_id,
                require_active=False,
            )
            target = deployment_qa_execution_target(conn, subject)
            reasons = stage_acceptance_blockers(
                conn,
                subject=subject,
                target=target,
                acceptance_qa_kind=DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
            )
        except (LookupError, ValueError) as exc:
            blockers.append(f"{label} could not be evaluated: {exc}")
            continue
        blockers.extend(f"{label}: {reason}" for reason in reasons)
    return blockers


__all__ = ["ItemReleaseQa", "item_qa_acceptance_blockers", "item_release_qa"]
