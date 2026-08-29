"""Collapsed local finalization side effects for done-transition."""

from __future__ import annotations

import sys
from typing import Callable, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.public_ref import format_item_ref
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import db_backend
from yoke_core.engines import done_transition_github_sync
from yoke_core.engines.done_transition_item_context import format_workflow_route


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _finalize_done_local_side_effects(
    item_id: int,
    release_category: str,
    title: str,
    item_project: str,
    env_name: str,
) -> None:
    """Run the collapsed local done finalization through the transport.

    The deployed_to resolution + conditional ``items.deployed_to`` update +
    ``release_entries`` upsert are relayed as ONE atomic
    ``done_transition.finalize_local_side_effects`` write so the whole
    transaction runs server-side on a single connection (over an https
    control plane as well as a local Postgres connection). Finalization is
    advisory: matching the inline ``connect()`` behavior, any failure
    degrades with a note and the item still reaches done — it never raises.
    """
    print("\n=== Step 6c/6d/7/10: Local done finalization ===")
    try:
        resp = call_dispatcher(
            function_id="done_transition.finalize_local_side_effects",
            target=TargetRef(kind="item", item_id=int(item_id)),
            payload={
                "release_category": release_category,
                "env_name": env_name,
                "title": title,
                "item_project": item_project,
            },
        )
    except Exception as exc:  # noqa: BLE001 - advisory; matches inline degrade
        print(f"Advisory: local done finalization failed: {exc}")
        return
    if not resp.success:
        message = resp.error.message if resp.error else "unknown error"
        print(f"Advisory: local done finalization partly skipped: {message}")
        return

    result = resp.result or {}
    deployed_to = str(result.get("deployed_to") or "")
    release_note = bool(result.get("release_note"))
    deploy_msg = (
        f"deployed_to={deployed_to}" if deployed_to else "deployed_to unchanged"
    )
    note_msg = "release note upserted" if release_note else "release note skipped"
    print(f"Local finalization: {deploy_msg}; {note_msg}.")


def _resolve_deployed_to(conn, item_id: int, env_name: str) -> str:
    if env_name:
        return env_name
    try:
        p = _p(conn)
        row = conn.execute(
            "SELECT COALESCE(i.deployment_flow, ''), "
            "COALESCE(e.name, f.target_tier, '') "
            "FROM items i "
            "LEFT JOIN deployment_flows f ON f.id = i.deployment_flow "
            "LEFT JOIN environments e ON e.id = f.target_environment_id "
            f"WHERE i.id = {p}",
            (item_id,),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        return ""
    if not row:
        return ""
    deploy_flow, environment = str(row[0] or ""), str(row[1] or "")
    if deploy_flow and deploy_flow != "null" and environment and environment != "null":
        return environment
    return ""


def _insert_release_note(
    conn,
    item_id: int,
    category: str,
    title: str,
    item_project: str,
) -> bool:
    from yoke_core.domain import release_notes as _release_notes

    try:
        _release_notes.cmd_insert(
            conn,
            int(item_id),
            category,
            title,
            project=item_project or None,
        )
    except db_backend.operational_error_types(conn):
        return False
    return True


def _report_closeout_failure(result, ref: str, old_status: str, exc: BaseException) -> None:
    """Name a closeout failure without disowning the transition that landed.

    Reporting the whole run as failed is what makes this dangerous: the
    status write and any merge are already committed, so an operator
    reading a non-zero exit reaches for a rollback that would desync the
    item from git.
    """
    detail = f"{type(exc).__name__}: {exc}"
    after = result.steps_completed[-1] if result.steps_completed else "6"
    result.warnings.append(
        {"kind": "closeout_incomplete", "after_step": after, "detail": detail}
    )
    print("\n=== Closeout incomplete ===", file=sys.stderr)
    print(f"  Transition: {ref} {old_status} -> done (committed)", file=sys.stderr)
    print(f"  Closeout: stopped after step {after} — {detail}", file=sys.stderr)
    print(
        "  The status write and any merge already landed. Re-run the done "
        "transition to finish closeout; do not roll the item back.",
        file=sys.stderr,
    )


def finish_done_transition(
    done_transition,
    result,
    *,
    result_file: str,
    item_id: int,
    title: str,
    old_status: str,
    workflow,
    repo_root,
    merge_ran: bool,
    public_ref: str | None = None,
    prune_lane: Optional[Callable[[], object]] = None,
) -> int:
    """Close out a done transition that has already committed, and report it.

    Every step here runs after the item's status reached ``done``, so the
    transition can no longer fail — only its closeout can. The exit code
    therefore names the transition, and a closeout that stops early is
    reported and recorded as a warning rather than turned into a failed run.

    ``prune_lane`` deletes the merged worktree and runs last, because this
    process may be executing out of that lane: its interpreter, its
    installed packages, and its import root all live there. Anything the
    closeout still has to import or read has to happen while the tree is
    still on disk.
    """
    ref = public_ref or format_item_ref(None, None, None, item_id=item_id)
    try:
        _run_closeout(
            done_transition,
            result,
            item_id=item_id,
            title=title,
            old_status=old_status,
            workflow=workflow,
            repo_root=repo_root,
            merge_ran=merge_ran,
            ref=ref,
            prune_lane=prune_lane,
        )
    except Exception as exc:  # noqa: BLE001 - the transition already committed
        _report_closeout_failure(result, ref, old_status, exc)
    result.write(result_file)
    print(f"RESULT_FILE={result_file}")
    return 0


def _run_closeout(
    done_transition,
    result,
    *,
    item_id: int,
    title: str,
    old_status: str,
    workflow,
    repo_root,
    merge_ran: bool,
    ref: str,
    prune_lane: Optional[Callable[[], object]],
) -> None:
    """Run every step that follows the committed status write."""
    print("\n=== Step 8: Sync done state to GitHub ===")
    done_transition_github_sync.apply_step_8(
        item_id, old_status, result, public_ref=ref,
    )
    # The scan addresses the item by its public ref: a digit string is a
    # project-local sequence, not items.id, so the internal id resolves
    # either nothing or the wrong row. The helper records "9" or
    # "9-degraded" itself.
    done_transition._apply_discovery_scan(ref, result)
    result.add_step("10")

    print("\n=== Step 11: Rebuild board ===")
    done_transition._rebuild_board_direct()
    result.add_step("11")

    print("\n=== Step 12: Commit ===")
    commit_ran = False
    diff = done_transition._run_git(["diff", "--cached", "--quiet"], capture=True)
    if diff.returncode != 0:
        commit = done_transition._run_git(
            ["commit", "-m", f"{ref}: {old_status} -> done"]
        )
        commit_ran = commit.returncode == 0
        if commit_ran:
            from yoke_core.engines.done_transition_snapshot import (
                ensure_snapshot_for_item,
            )

            ensure_snapshot_for_item(item_id)
    result.add_step("12")

    print("\n=== Step 13: Push ===")
    if commit_ran or merge_ran:
        push_branch = done_transition._get_base_branch("", repo_root)
        push = done_transition._run_git(["push", "origin", push_branch])
        if push.returncode != 0:
            print("Push failed - attempting rebase and retry...")
            done_transition._run_git(["pull", "--rebase", "origin", push_branch])
            retry = done_transition._run_git(["push", "origin", push_branch])
            if retry.returncode != 0:
                print(
                    "Warning: git push failed after done-transition commit. "
                    "Local is ahead of origin."
                )
    else:
        print("No merge commit or done-transition commit produced - skipping push.")
    result.add_step("13")

    print("\n=== Step 14: Report ===")
    print("==========================================")
    print(f"{ref} ({title}): {old_status} -> done")
    print("==========================================\n")
    print(format_workflow_route(workflow))
    result.add_step("14")

    if prune_lane is not None:
        prune_lane()
    result.add_step("4a")


__all__ = ["_finalize_done_local_side_effects", "finish_done_transition"]
