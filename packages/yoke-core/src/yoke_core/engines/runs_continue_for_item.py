"""Carry a prepared release across the merge that completes its pair.

A prepared run is a promise made before the work landed: it names the flow
and the environment but not the commit, because the merge that creates that
commit has not happened yet. This is the other half of the promise. It runs
at the merge close-out of every item the run is waiting on, and it is the
LAST such merge that finally moves — the producer's own merge is not enough
when a consumer in another project still has to land, and continuing there
would publish a product whose consumer is still the old one.

Nothing here decides what "landed" means on its own. The run's composition is
re-validated with no exemption, so the same dependency evaluation that
refused to compose the run before the pair merged is what now says it may
proceed, reading the blocker's ``merged_at`` rather than a status field. The
first merge in a pair therefore reports what it is still waiting for and
changes nothing; the last one binds the lineage.

Binding is where this stops. Executing a run needs the project's deploy lock
and a direct control-plane connection, and a merging worker holds neither —
so the completed pair is handed to the session that does hold that authority
as a durable Fleet message, keyed so that re-running this after a crash, or
running it once per member of the same pair, delivers exactly one hand-off
rather than one per attempt. No merge acquires deploy authority, and a merge
with no prepared run waiting on it takes none of this path at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from yoke_core.domain.deploy_lock import AMBIENT_SESSION
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.deployment_run_lineage_rebind import (
    lineage_of,
    refuse_lineage_write,
)
from yoke_core.domain.deployment_run_pair_obligations import (
    prepared_runs_awaiting_item,
    run_item_ids,
    split_runs_by_target_environment,
)
from yoke_core.domain.deployment_runs_validation import cmd_validate_composition
from yoke_core.domain.item_ref_columns import render_column_item_ref


#: No prepared run is waiting on this item. The ordinary case for an ordinary
#: merge, and explicitly not a failure.
OUTCOME_NONE = "no_prepared_run"
#: A prepared run exists and is still waiting for a partner to merge.
OUTCOME_WAITING = "waiting_for_pair"
#: The pair is complete and the run now names the commit it will deploy.
OUTCOME_BOUND = "bound_and_handed_off"


@dataclass
class ContinueResult:
    """What one merge did, or did not, do to a prepared release."""

    ok: bool
    outcome: str
    run_id: Optional[str] = None
    release_lineage: Optional[str] = None
    waiting_on: List[str] = field(default_factory=list)
    handed_off_to: Optional[str] = None
    message_id: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    #: One entry per prepared run this merge advanced. A stage/production
    #: pair legitimately carries two; a single run carries one.
    runs: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        out: dict[str, Any] = {
            "ok": self.ok,
            "outcome": self.outcome,
            "run_id": self.run_id,
            "release_lineage": self.release_lineage,
            "waiting_on": list(self.waiting_on),
        }
        if self.runs:
            out["runs"] = list(self.runs)
        if self.handed_off_to is not None:
            out["handed_off_to"] = self.handed_off_to
        if self.message_id is not None:
            out["message_id"] = self.message_id
        if not self.ok:
            out["error"] = self.error
            out["error_code"] = self.error_code
        return out


def _merge_identity(conn: Any, item_id: int) -> str:
    from yoke_core.domain.dash_execution import DASH_EVIDENCE_SECTION
    from yoke_core.domain.item_json_sections import read_json_section

    evidence = read_json_section(
        conn,
        item_id=int(item_id),
        section=DASH_EVIDENCE_SECTION,
    )
    return str((evidence or {}).get("merge_sha") or "").strip()


def _project_of_run(conn: Any, run_id: str) -> tuple[int, str]:
    from yoke_core.domain.project_identity import resolve_project_slug

    row = conn.execute(
        "SELECT project_id FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    project_id = int(row["project_id"] if hasattr(row, "keys") else row[0])
    return project_id, resolve_project_slug(conn, project_id)


def _pending_partner_refs(conn: Any, run_id: str) -> List[str]:
    from yoke_core.domain.deployment_run_pair_obligations import (
        split_pending_pair_merges,
    )

    pending, _ = split_pending_pair_merges(conn, run_item_ids(conn, run_id))
    return [obligation.describe() for obligation in pending]


def _continue_one_run(
    conn: Any,
    *,
    run_id: str,
    item_id: int,
    release_lineage: Optional[str],
    session_id: Optional[str],
    db_path: Optional[str],
) -> ContinueResult:
    """Advance exactly one prepared run, or report why it cannot move."""
    ok, message = cmd_validate_composition(run_id, db_path)
    if not ok:
        return ContinueResult(
            ok=True,
            outcome=OUTCOME_WAITING,
            run_id=run_id,
            waiting_on=_pending_partner_refs(conn, run_id) or [message],
        )

    lineage = (release_lineage or "").strip()
    if not lineage:
        for member in run_item_ids(conn, run_id):
            lineage = _merge_identity(conn, member)
            if lineage:
                break
    if not lineage:
        return ContinueResult(
            ok=False,
            outcome=OUTCOME_WAITING,
            run_id=run_id,
            error=(
                f"prepared run {run_id} has no merge identity to bind: no "
                "member item recorded a merge commit. Record Dash merge "
                "evidence, or pass --release-lineage with the exact "
                "merge commit"
            ),
            error_code="merge_identity_missing",
        )

    refusal = refuse_lineage_write(conn, run_id, lineage)
    if refusal is not None:
        return ContinueResult(
            ok=False,
            outcome=OUTCOME_WAITING,
            run_id=run_id,
            error=refusal,
            error_code="lineage_write_refused",
        )
    if lineage_of(conn, run_id) != lineage:
        conn.execute(
            "UPDATE deployment_runs SET release_lineage=%s WHERE id=%s",
            (lineage, run_id),
        )
        conn.commit()

    from yoke_core.engines.runs_release_handoff import hand_off_prepared_run

    handoff = hand_off_prepared_run(
        conn,
        run_id=run_id,
        release_lineage=lineage,
        project=_project_of_run(conn, run_id),
        session_id=session_id,
    )
    return ContinueResult(
        ok=True,
        outcome=OUTCOME_BOUND,
        run_id=run_id,
        release_lineage=lineage,
        handed_off_to=handoff.recipient,
        message_id=handoff.message_id,
    )


def _aggregate(outcomes: List[ContinueResult]) -> ContinueResult:
    """One answer for the whole pair, keeping each run's own outcome.

    A half-advanced pair is the state worth naming precisely, so the summary
    reports the first failure and still carries every run it did move.
    """
    if len(outcomes) == 1:
        only = outcomes[0]
        only.runs = [entry.to_dict() for entry in outcomes]
        return only
    failed = next((entry for entry in outcomes if not entry.ok), None)
    summary = failed or next(
        (entry for entry in outcomes if entry.outcome == OUTCOME_WAITING),
        outcomes[0],
    )
    return ContinueResult(
        ok=summary.ok,
        outcome=summary.outcome,
        run_id=summary.run_id,
        release_lineage=summary.release_lineage,
        waiting_on=list(summary.waiting_on),
        handed_off_to=summary.handed_off_to,
        message_id=summary.message_id,
        error=summary.error,
        error_code=summary.error_code,
        runs=[entry.to_dict() for entry in outcomes],
    )


def continue_for_item(
    item_id: int,
    *,
    release_lineage: Optional[str] = None,
    session_id: Optional[str] = AMBIENT_SESSION,
    db_path: Optional[str] = None,
) -> ContinueResult:
    """Advance any prepared run this item's merge completes."""
    if session_id == AMBIENT_SESSION:
        from yoke_core.domain.session_ambient_identity import (
            resolve_ambient_session_id,
        )

        session_id = resolve_ambient_session_id()
    conn = connect(db_path)
    try:
        run_ids = prepared_runs_awaiting_item(conn, int(item_id))
        if not run_ids:
            return ContinueResult(ok=True, outcome=OUTCOME_NONE)
        distinct, duplicates = split_runs_by_target_environment(conn, run_ids)
        if duplicates:
            groups = "; ".join(", ".join(group) for group in duplicates)
            return ContinueResult(
                ok=False,
                outcome=OUTCOME_WAITING,
                error=(
                    f"item {render_column_item_ref(conn, item_id)} advances "
                    f"more than one prepared run for the same target "
                    f"environment ({groups}); only one of them can be that "
                    "environment's release. Cancel the runs that no longer "
                    "apply with `yoke deployment-runs terminalize RUN-ID "
                    "--disposition cancelled --reason TEXT`"
                ),
                error_code="duplicate_prepared_run",
            )
        outcomes = [
            _continue_one_run(
                conn,
                run_id=run_id,
                item_id=int(item_id),
                release_lineage=release_lineage,
                session_id=session_id,
                db_path=db_path,
            )
            for run_id in distinct
        ]
        return _aggregate(outcomes)
    finally:
        conn.close()


__all__ = [
    "OUTCOME_BOUND",
    "OUTCOME_NONE",
    "OUTCOME_WAITING",
    "ContinueResult",
    "continue_for_item",
]
