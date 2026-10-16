"""Current settlement prerequisites, without preparing or closing members.

Run-bound QA counts describe a different population. This projection retains
that boundary and reads member facts only once settlement has begun. It never
materializes plans, prepares transitions, commits, or replays effects.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.deployment_run_settlement_refusal import (
    HELD_WITH_RUN,
    member_readiness_reason,
)
from yoke_core.domain.qa_item_obligation_queries import unsatisfied_blocking_many
from yoke_core.domain.schema_common import _column_exists


@dataclass(frozen=True)
class MemberCompletion:
    item_id: int
    public_ref: str
    state: str
    detail: str

    def describe(self) -> str:
        return f"member closure {self.public_ref} ({self.state}): {self.detail}"


@dataclass(frozen=True)
class CompletionPreview:
    members: tuple[MemberCompletion, ...] = ()
    settling: bool = False
    unavailable: str = ""

    @property
    def blocked(self) -> bool:
        return bool(self.unavailable) or any(
            member.state == "blocked" for member in self.members
        )

    @property
    def lines(self) -> tuple[str, ...]:
        if self.unavailable:
            return (self.unavailable,)
        if self.settling and not self.members:
            return ("member closure: statuses settled; finalization effects pending",)
        return tuple(member.describe() for member in self.members)

    def recovery(self, run_id: str) -> str:
        if self.unavailable:
            return (
                f"member_closure_unavailable: restore the named member contract or "
                f"control-plane read, then reread `yoke deployment-runs get {run_id}`; "
                "do not infer completion or dispatch another driver."
            )
        if self.blocked:
            return (
                "run_settlement_blocked: satisfy the named member gates on their "
                "declared targets. Atomic siblings need no separate repair. "
                "Settlement continues after the last blocker clears; repeating "
                "the success write cannot supply missing acceptance. "
                f"Read `yoke deployment-runs get {run_id}`."
            )
        if self.members:
            return (
                "Member close-out remains pending; read each named item's done "
                "gates. Other-target debt stays owed after this run delivers; "
                "delivery does not accept or waive it."
            )
        if self.settling:
            return (
                "Member statuses are settled; finalization effects remain pending. "
                f"Read `yoke deployment-runs get {run_id}` and its driver progress; "
                "recover a stopped driver before re-driving finalization."
            )
        return ""


def completion_preview(
    conn: Any, run_id: str, *, run: dict[str, Any] | None = None
) -> CompletionPreview:
    """Share final membership, target deferral, and readiness with settlement."""
    if run is None:
        if not _column_exists(conn, "deployment_runs", "settling_at"):
            return CompletionPreview()
        row = conn.execute(
            "SELECT status,settling_at FROM deployment_runs WHERE id=%s", (run_id,)
        ).fetchone()
        if row is None:
            return CompletionPreview()
        run = dict(row)
    if run["status"] != "executing" or not run["settling_at"]:
        return CompletionPreview()
    try:
        return _read_members(conn, run_id)
    except (LookupError, ValueError) as exc:
        return CompletionPreview(
            settling=True,
            unavailable=f"member_closure_unavailable: {exc}",
        )


def _read_members(conn: Any, run_id: str) -> CompletionPreview:
    from yoke_core.domain.deployment_run_collective_finalization import (
        _split_waiting_members,
    )
    from yoke_core.domain.deployment_member_post_deploy_admission import (
        requirement_target_environment,
    )

    required, deferred = _split_waiting_members(conn, run_id)
    members = required + deferred
    obligations = unsatisfied_blocking_many(
        conn, item_ids=(member["item_id"] for member in members), target_status="done"
    )
    deferred_ids = {member["item_id"] for member in deferred}
    entries = []
    for member in members:
        item_id = int(member["item_id"])
        blocking = obligations[item_id]
        reason = member_readiness_reason(conn, run_id, member, blocking=blocking)
        if not reason:
            from yoke_core.domain.delivery_member_close_steps import (
                member_close_evidence_refusal,
            )
            from yoke_core.domain.closure_status_gate import evaluate

            reason = member_close_evidence_refusal(
                conn, item_id=item_id, delivery_pending=True
            )
            closure = evaluate(item_id=item_id, conn=conn)
            if closure:
                reason = " ".join(
                    filter(
                        None,
                        (reason, closure["error"], closure.get("remediation_hint")),
                    )
                )
        targets = [
            f"requirement #{row['id']} ({row['qa_kind']}, phase={row['qa_phase']}, "
            f"target={requirement_target_environment(row.get('target_env'), row.get('execution_target_json')) or 'unspecified'})"
            for row in blocking.rows
        ]
        if targets:
            reason += " " + "; ".join(targets)
        state = (
            "deferred to other target"
            if item_id in deferred_ids
            else ("blocked" if reason else "close-out pending")
        )
        entries.append(
            MemberCompletion(item_id, str(member["public_ref"]), state, reason)
        )
    if any(entry.state == "blocked" for entry in entries):
        entries = [
            MemberCompletion(
                entry.item_id, entry.public_ref, "held atomically", HELD_WITH_RUN
            )
            if entry.state == "close-out pending"
            else entry
            for entry in entries
        ]
    else:
        entries = [
            MemberCompletion(
                entry.item_id,
                entry.public_ref,
                entry.state,
                entry.detail
                or "delivery/QA prerequisites read clear; pinned close-out gates and effects still need to finish",
            )
            for entry in entries
        ]
    return CompletionPreview(tuple(entries), settling=True)


def run_completion_diagnostics(run_id: str) -> dict[str, Any]:
    """Additional, separately labelled diagnostics for the registered run read."""
    with connect() as conn:
        preview = completion_preview(conn, run_id)
    return {
        "members": [asdict(member) for member in preview.members],
        "lines": list(preview.lines),
        "settling": preview.settling,
        "blocked": preview.blocked,
        "recovery": preview.recovery(run_id),
    }
