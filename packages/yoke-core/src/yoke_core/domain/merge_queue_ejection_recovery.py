"""Recover queue-only conflicts from durable queue order and file evidence."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from yoke_contracts.timestamps import parse_instant

from yoke_core.domain.merge_queue_failed_train import unchanged_failed_train_refusal
from yoke_core.domain.merge_queue_landing_episode import clear_episode, restore_episode
from yoke_core.engines.merge_worktree_pr_files import read_pr_changed_files
from yoke_core.engines.merge_worktree_pr_queue import (
    enter_merge_queue,
    read_queue_members,
)


def conflicts_with_base(readback: Any) -> bool:
    member = readback.membership
    if member is not None and member.mergeable in {"MERGEABLE", "CONFLICTING"}:
        return member.mergeable == "CONFLICTING"
    return bool(readback.state and readback.state.merge_state_status.lower() == "dirty")


def recovery_instruction(readback: Any, *, target: str) -> str:
    if conflicts_with_base(readback):
        return (
            f"base_conflict: it conflicts with its base branch; rebase the lane onto {target}, re-run the "
            "verification gate, and re-run `yoke merge item`"
        )
    recovery = readback.queue_recovery
    if recovery.get("message"):
        return recovery["message"]
    member = readback.membership
    if (
        member is not None
        and member.entry_state == "UNMERGEABLE"
        and member.mergeable != "MERGEABLE"
    ):
        return (
            "queue_mergeability_unknown: wait for GitHub to recompute mergeable; "
            "if CONFLICTING, rebase the lane onto "
            + target
            + ", re-run the verification gate "
            "and re-run `yoke merge item`; if MERGEABLE, re-run `yoke merge item` after the entries ahead leave; a failed train still requires a correction or one recorded --retry-flake claim."
        )
    if member is not None and member.entry_state == "UNMERGEABLE":
        return (
            "queue_conflict: mergeable against the base; wait for entries ahead "
            "to land or leave, then re-read mergeable. If CONFLICTING, rebase, "
            "re-verify and re-run `yoke merge item`; if MERGEABLE, re-run `yoke merge item`; a failed train requires a correction or one recorded --retry-flake claim."
        )
    return ""


def _ahead_snapshot(ctx, pr_number, members, *, read_files):
    ahead = []
    for member in members:
        if member.pr_num == pr_number:
            break
        ahead.append(member)
    if not ahead:
        return []
    own_files, error = read_files(ctx, pr_number)
    if error or own_files is None:
        raise ValueError(f"queue_recovery_files_unreadable: PR #{pr_number}: {error}")
    snapshot = []
    for member in ahead:
        files, error = read_files(ctx, member.pr_num)
        if error or files is None:
            raise ValueError(
                f"queue_recovery_files_unreadable: PR #{member.pr_num}: {error}"
            )
        snapshot.append(
            {
                "pr_number": member.pr_num,
                "shared_files": sorted(set(own_files) & set(files)),
            }
        )
    return snapshot


def recover_ejection(
    conn,
    row,
    ctx,
    readback,
    *,
    now,
    read_queue=read_queue_members,
    read_files=read_pr_changed_files,
    enqueue=enter_merge_queue,
    reread=None,
    failed_train=unchanged_failed_train_refusal,
):
    """Snapshot predecessors while queued; recover only the same unchanged head.

    GitHub remains the authority for mergeability. Shared files explain why a
    train may fail; they never prove that two changes conflict.
    """
    from yoke_core.domain.merge_queue_landing_record import read_landing_record

    state, member = readback.state, readback.membership
    if state is None or state.merged or state.closed or member is None:
        return readback
    pr_number = str(row["merge_queue_pr_number"])
    lock_recovery(conn, int(row["id"]))
    previous = read_landing_record(conn, int(row["id"]))
    recovery = (
        dict(previous.recovery)
        if previous
        and previous.pr_number == pr_number
        and previous.head_sha == state.head_sha
        else {}
    )
    if recovery.get("action") == "held":
        return replace(readback, queue_recovery=recovery)
    dropped = not readback.admitted() and not readback.undetermined()
    if (
        dropped
        and not member.in_queue
        and row.get("attempt")
        and row.get("merge_queue_enqueued_at")
    ):
        clear_episode(conn, row, parse_instant(row["merge_queue_enqueued_at"]))
    if conflicts_with_base(readback) or readback.failed_required:
        recovery.pop("message", None)
        return replace(
            readback,
            queue_recovery={
                **recovery,
                "action": "rebase" if conflicts_with_base(readback) else "blocked",
            },
        )
    recovering = recovery.get("action") in {"waiting", "retry"}
    queue_only = member.entry_state == "UNMERGEABLE" and member.mergeable == "MERGEABLE"
    if (
        not member.in_queue
        and not recovering
        and not (dropped and recovery.get("ahead"))
    ):
        return readback
    members, error = read_queue(ctx, base_branch=ctx.args.target)
    if error or members is None:
        if not dropped and not recovering:
            return readback
        return replace(
            readback,
            queue_recovery={
                **recovery,
                "action": "retry",
                "message": f"queue_recovery_unreadable: {error}; restore GitHub queue reads and retry observation; no re-enqueue was sent.",
            },
        )
    try:
        if not dropped and not recovering:
            ahead_numbers = []
            for entry in members:
                if entry.pr_num == pr_number:
                    break
                ahead_numbers.append(entry.pr_num)
            if ahead_numbers != [
                entry["pr_number"] for entry in recovery.get("ahead", [])
            ]:
                recovery = {}
        if "ahead" not in recovery:
            recovery["ahead"] = _ahead_snapshot(
                ctx, pr_number, members, read_files=read_files
            )
    except ValueError as exc:
        return replace(
            readback,
            queue_recovery={
                **recovery,
                "action": "retry",
                "message": f"{exc}; restore GitHub file reads and retry observation.",
            },
        )
    if not dropped and not recovering:
        return replace(readback, queue_recovery={**recovery, "action": "watching"})
    if not (recovering or queue_only or recovery.get("ahead")):
        return readback
    current = {m.pr_num for m in members}
    waiting = [
        entry for entry in recovery.get("ahead", []) if entry["pr_number"] in current
    ]
    if waiting or member.in_queue or member.mergeable != "MERGEABLE":
        details = "; ".join(
            f"PR #{entry['pr_number']} (shared files: {', '.join(entry['shared_files']) or 'none'})"
            for entry in waiting
        )
        message = f"queue_conflict: wait for {details or 'GitHub to remove the unmergeable entry and recompute mergeability'} to land or leave; then re-read mergeable, rebase and re-verify if CONFLICTING, or re-enqueue unchanged if MERGEABLE."
        return replace(
            readback,
            queue_recovery={**recovery, "action": "waiting", "message": message},
        )
    if readback.required_checks is None:
        return replace(
            readback,
            queue_recovery={
                **recovery,
                "action": "retry",
                "message": "queue_recovery_checks_unreadable: restore required-check reads and retry observation; no re-enqueue was sent.",
            },
        )
    refusal = failed_train(
        ctx, pr_number, lane_head=state.head_sha, base_branch=ctx.args.target
    )
    if refusal:
        return replace(readback, queue_recovery={
            **recovery, "action": "blocked", "message": refusal,
        })
    outcome = enqueue(ctx, pr_number, expected_head_sha=state.head_sha)
    if not outcome.success:
        return replace(
            readback,
            queue_recovery={
                **recovery,
                "action": "blocked",
                "message": f"queue_reenqueue_failed: {outcome.error_detail}; restore GitHub App Contents: write and Pull requests: write installation permissions and token scopes, then re-run `yoke merge item`.",
            },
        )
    from yoke_core.domain.merge_queue_reentry_receipt import record_reentry

    record_reentry(conn, int(row["id"]), pr_number, state.head_sha, now)
    # Record the new arming episode before any subsequent read can fail.
    if row.get("merge_queue_enqueued_at"):
        clear_episode(conn, row, parse_instant(row["merge_queue_enqueued_at"]))
    restore_episode(conn, row, now)
    row["merge_queue_enqueued_at"] = now
    fresh = reread(ctx, pr_number)
    return replace(
        fresh,
        queue_recovery={
            **recovery,
            "action": "rearmed",
            "message": "queue_reenqueued: predecessors left the queue and the unchanged head is mergeable against the base; merge-when-ready requested again.",
        },
    )


def lock_recovery(conn, item_id):
    """Serialize observer re-arming with an explicit holder hold."""
    from yoke_core.domain import db_backend

    postgres = db_backend.connection_is_postgres(conn)
    marker = "%s" if postgres else "?"
    suffix = " FOR UPDATE" if postgres else ""
    conn.execute(
        f"SELECT item_id FROM merge_queue_landing_records WHERE item_id={marker}{suffix}",
        (item_id,),
    ).fetchone()


def hold_with_recovery_suspended(item_id, pr_number, hold):
    """An explicit hold wins over automatic queue recovery until a fresh arming."""
    from yoke_core.domain import db_helpers
    from yoke_core.domain.merge_queue_landing_record import (
        read_landing_record,
        write_landing_record,
    )

    with db_helpers.connect() as conn:
        lock_recovery(conn, item_id)
        record = read_landing_record(conn, item_id)
        if record and record.pr_number == pr_number:
            write_landing_record(conn, replace(record, recovery={"action": "held"}))
        result = hold()
        conn.commit()
        return result


def snapshot_recovery(ctx, pr_number, readback):
    """Attach queue-order evidence to an immediate admission refusal."""
    member = readback.membership
    if (
        member is None
        or member.entry_state != "UNMERGEABLE"
        or member.mergeable != "MERGEABLE"
    ):
        return readback
    members, error = read_queue_members(ctx, base_branch=ctx.args.target)
    if error or members is None:
        return replace(
            readback,
            queue_recovery={
                "message": f"queue_recovery_unreadable: {error}; restore GitHub queue reads and re-run `yoke merge item`."
            },
        )
    try:
        ahead = _ahead_snapshot(
            ctx, pr_number, members, read_files=read_pr_changed_files
        )
    except ValueError as exc:
        return replace(
            readback,
            queue_recovery={
                "message": f"{exc}; restore GitHub file reads and re-run `yoke merge item`."
            },
        )
    details = "; ".join(
        f"PR #{entry['pr_number']} (shared files: {', '.join(entry['shared_files']) or 'none'})"
        for entry in ahead
    )
    return replace(
        readback,
        queue_recovery={
            "ahead": ahead,
            "message": f"queue_conflict: wait for {details or 'the entries ahead'} to land or leave, then re-read mergeable; CONFLICTING requires rebase and verification before `yoke merge item`; MERGEABLE permits re-enqueue unchanged.",
        },
    )
