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
from yoke_core.domain.deployment_qa_stage_acceptance import (
    STAGE_ACCEPTED,
    STAGE_DISCHARGED,
    stage_acceptance,
    stage_acceptance_blockers,
)
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


def _is_qa_stage(stage: Mapping[str, Any]) -> bool:
    return (
        stage.get("stage_kind") == STAGE_KIND_QA
        or stage.get("step_runner") == QA_STEP_RUNNER
    )


def _pinned_stages(conn: Any, run_id: str) -> list[dict[str, Any]]:
    """Every stage the run pinned, in order, or ``[]`` for a legacy flow."""
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
    return [dict(stage) for stage in stages if isinstance(stage, Mapping)]


def pinned_stages(conn: Any, run_id: str) -> list[dict[str, Any]]:
    """Every stage the run pinned, for a caller that answers for several of
    its members and passes the result back into :func:`current_item_qa`."""
    return _pinned_stages(conn, str(run_id))


def _pinned_qa_stages(conn: Any, run_id: str) -> list[dict[str, Any]]:
    """The run's own pinned QA stages, or ``[]`` for a legacy definition."""
    return [stage for stage in _pinned_stages(conn, run_id) if _is_qa_stage(stage)]


@dataclass(frozen=True)
class ItemStageQa:
    """One member's standing at the item QA stage it is answerable for now.

    A card asks a narrower question than the release gate does. The gate must
    know whether every scoped obligation in the run is met, future stages
    included, because that is what closing the item means. A card is saying
    where this member stands *today*: folding a production QA stage the run
    has not reached into that answer reports every healthy item as unclear,
    and folding a run-scoped stage into it reports the batch's shared wait as
    this member's own problem. Shared progress is the run's to show.
    """

    stage: str
    state: str
    blockers: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return self.state in (STAGE_ACCEPTED, STAGE_DISCHARGED)

    @property
    def reason(self) -> str:
        return self.blockers[0] if self.blockers else ""


def _applicable_item_stage(
    stages: list[dict[str, Any]], current_stage: str
) -> dict[str, Any] | None:
    """The item-scoped QA stage this member is answerable for right now.

    The one the run is standing on, else the last one it has already passed.
    Before the run reaches any, there is no item QA to report — which is not
    the same as reporting that none passed.
    """
    item_stages = [
        (index, stage)
        for index, stage in enumerate(stages)
        if _is_qa_stage(stage) and stage.get("scope") == "item"
    ]
    if not item_stages:
        return None
    positions = {
        str(stage.get("name") or ""): index for index, stage in enumerate(stages)
    }
    # An unrecognized current stage (a finished run's terminal label) means
    # the run is past every stage it pinned, so the last one answers.
    here = positions.get(str(current_stage), len(stages))
    reached = [stage for index, stage in item_stages if index <= here]
    return reached[-1] if reached else None


def current_item_qa(
    conn: Any,
    *,
    run_id: str,
    item_id: int,
    current_stage: str,
    stages: list[dict[str, Any]] | None = None,
) -> ItemStageQa | None:
    """This member's standing at the item QA stage now answering for it.

    *stages* is this run's already-read :func:`pinned_stages`. A caller
    answering for several members of one release passes it so the run's own
    definition is read once for the set instead of once per member.
    """
    pinned = _pinned_stages(conn, str(run_id)) if stages is None else stages
    stage = _applicable_item_stage(pinned, current_stage)
    if stage is None:
        return None
    stage_name = str(stage.get("name") or "")
    subject = deployment_qa_stage_subject(
        conn,
        run_id=str(run_id),
        stage_name=stage_name,
        member_item_id=int(item_id),
        require_active=False,
    )
    acceptance = stage_acceptance(
        conn,
        subject=subject,
        target=deployment_qa_execution_target(conn, subject),
        acceptance_qa_kind=DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
    )
    return ItemStageQa(
        stage=stage_name,
        state=acceptance.state,
        blockers=acceptance.blockers,
    )


def item_qa_acceptance_blockers(conn: Any, *, run_id: str, item_id: int) -> list[str]:
    """Every unsatisfied scoped QA verdict this item still owes in the run.

    Release-wide on purpose: closing an item means the whole run answered for
    it, so this walks every pinned QA stage rather than only the current one.
    """
    return _stage_blockers(
        conn, str(run_id), int(item_id), _pinned_qa_stages(conn, str(run_id))
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


__all__ = [
    "ItemStageQa",
    "current_item_qa",
    "item_qa_acceptance_blockers",
    "pinned_stages",
]
