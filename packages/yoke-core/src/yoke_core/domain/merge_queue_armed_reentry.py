"""Form an armed, ready landing's missing entry once per unchanged head."""

from dataclasses import replace

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.merge_github_queue import enqueue_pull_request
from yoke_core.domain.merge_queue_landing_episode import clear_episode, restore_episode
from yoke_core.domain.merge_queue_reentry_receipt import read_reentry, record_reentry


def recover_armed_ready(
    conn, row, ctx, readback, *, previous, now, enqueue, reread, failed_train
):
    state = readback.state
    pr_number = str(row["merge_queue_pr_number"])

    def blocked(message):
        return replace(
            readback, queue_recovery={"action": "blocked", "message": message}
        )

    if not state.head_sha:
        return blocked(
            "queue_reentry_head_unreadable: restore PR head reads and retry observation; no enqueue was sent."
        )
    if previous and (
        previous.pr_number != pr_number or previous.head_sha != state.head_sha
    ):
        return blocked(
            "queue_reentry_head_moved: the observed PR/head changed; verify the lane and re-run `yoke merge item`."
        )
    receipt = read_reentry(conn, int(row["id"]), pr_number, state.head_sha)
    if receipt:
        return blocked(
            f"GitHub accepted re-entry at {state.head_sha} but formed no entry "
            f"(accepted {receipt['accepted_at']}); inspect the PR timeline, correct the lane, "
            "and re-run verification before `yoke merge item`; no second automatic enqueue was sent."
        )
    if previous and previous.recovery.get("action") == "blocked":
        return replace(readback, queue_recovery=previous.recovery)
    if readback.required_checks is None:
        return blocked(
            "queue_recovery_checks_unreadable: restore required-check reads and retry observation; no enqueue was sent."
        )
    refusal = failed_train(
        ctx, pr_number, lane_head=state.head_sha, base_branch=ctx.args.target
    )
    if refusal:
        return blocked(refusal)
    outcome = (enqueue or enqueue_pull_request)(
        ctx, pr_number, expected_head_sha=state.head_sha
    )
    if outcome.success:
        record_reentry(conn, int(row["id"]), pr_number, state.head_sha, now)
    fresh = reread(ctx, pr_number)
    if not (fresh.merged or (fresh.membership and fresh.membership.in_queue)):
        detail = (
            outcome.error_detail or "GitHub returned success but formed no queue entry"
        )
        return blocked(
            f"queue_reenqueue_failed: {detail}; inspect GitHub's PR timeline and permissions, "
            "correct the refusal and re-run `yoke merge item`."
        )
    if fresh.state and fresh.state.head_sha != state.head_sha:
        return blocked(
            "queue_reentry_head_moved: GitHub now reports a different head; verify the lane and re-run `yoke merge item`."
        )
    if not outcome.success:
        record_reentry(conn, int(row["id"]), pr_number, state.head_sha, now)
    if row.get("merge_queue_enqueued_at"):
        clear_episode(conn, row, parse_instant(row["merge_queue_enqueued_at"]))
    restore_episode(conn, row, now)
    row["merge_queue_enqueued_at"] = now
    return replace(fresh, queue_recovery={"action": "rearmed"})
