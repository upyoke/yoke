"""Collapsed local finalization side effects for done-transition."""

from __future__ import annotations

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import db_backend
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
            "SELECT COALESCE(i.deployment_flow, ''), COALESCE(f.target_env, '') "
            "FROM items i "
            "LEFT JOIN deployment_flows f ON f.id = i.deployment_flow "
            f"WHERE i.id = {p}",
            (item_id,),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        return ""
    if not row:
        return ""
    deploy_flow, target_env = str(row[0] or ""), str(row[1] or "")
    if deploy_flow and deploy_flow != "null" and target_env and target_env != "null":
        return target_env
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
) -> int:
    """Rebuild, persist, push, and report a successful done transition."""
    print("\n=== Step 11: Rebuild board ===")
    done_transition._rebuild_board_direct()
    result.add_step("11")

    print("\n=== Step 12: Commit ===")
    commit_ran = False
    diff = done_transition._run_git(["diff", "--cached", "--quiet"], capture=True)
    if diff.returncode != 0:
        commit = done_transition._run_git(
            ["commit", "-m", f"YOK-{item_id}: {old_status} -> done"]
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
    print(f"YOK-{item_id} ({title}): {old_status} -> done")
    print("==========================================\n")
    print(format_workflow_route(workflow))
    result.add_step("14")
    result.write(result_file)
    print(f"RESULT_FILE={result_file}")
    return 0


__all__ = ["_finalize_done_local_side_effects", "finish_done_transition"]
