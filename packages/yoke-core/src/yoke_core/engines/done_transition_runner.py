"""Done-transition state machine."""

from __future__ import annotations

import os
import sys

from yoke_core.domain import db_backend
from yoke_core.engines.done_transition_preconditions import enforce_preconditions as _enforce_preconditions
from yoke_core.engines.done_transition_runtime import _reseat_runtime_paths

def _parent():
    from yoke_core.engines import done_transition as _dt
    return _dt

def run(
    item_id: int,
    *,
    env_name: str = "",
    skip_simulation: bool = False,
    skip_deploy: bool = False,
    skip_qa: bool = False,
) -> int:
    """Execute the done-transition state machine.

    This is the semantic core. Returns the process exit code.
    """
    mw = _parent()
    TransitionResult = mw.TransitionResult
    _resolve_repo_root = mw._resolve_repo_root
    _connect = mw._connect
    _resolve_project_context = mw._resolve_project_context
    _query_item_field = mw._query_item_field
    _get_base_branch = mw._get_base_branch
    _check_simulation_gate = mw._check_simulation_gate
    _check_merge_guard = mw._check_merge_guard
    _check_empty_branch = mw._check_empty_branch
    _check_recovery = mw._check_recovery
    _handle_resume_from_step6 = mw._handle_resume_from_step6
    _handle_already_done = mw._handle_already_done
    _pre_merge_commit = mw._pre_merge_commit
    _check_deployment_redirect = mw._check_deployment_redirect
    _do_merge = mw._do_merge
    _update_item_direct = mw._update_item_direct
    _run_git = mw._run_git
    _cleanup_stale_branches = mw._cleanup_stale_branches
    _verify_cwd_after_merge = mw._verify_cwd_after_merge
    _schema_gate = mw._schema_gate
    _check_deployment_flow_guard = mw._check_deployment_flow_guard
    _cross_project_commit_guard = mw._cross_project_commit_guard
    _populate_merged_at = mw._populate_merged_at
    _update_status_to_done = mw._update_status_to_done
    _cascade_epic_tasks_to_done = mw._cascade_epic_tasks_to_done
    _finalize_done_local_side_effects = mw._finalize_done_local_side_effects
    _sync_done_item_direct = mw._sync_done_item_direct
    _apply_discovery_scan = mw._apply_discovery_scan
    _rebuild_board_direct = mw._rebuild_board_direct

    result = TransitionResult(item=f"YOK-{item_id}")
    result_file = os.path.join(
        os.environ.get("TMPDIR", "/tmp"),
        f"done-transition-result.YOK-{item_id}.json",
    )

    repo_root = _resolve_repo_root()
    if not repo_root:
        return result.fail(result_file, 2, "1")
    os.chdir(repo_root)
    sys.path[0] = str(repo_root)
    _reseat_runtime_paths(repo_root)
    result.add_step("1")
    print(f"YOKE_REPO_ROOT={repo_root}")
    with _connect() as conn:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            "SELECT i.id, i.title, i.status, i.worktree, i.type, i.github_issue, p.slug AS project "
            "FROM items i LEFT JOIN projects p ON p.id = i.project_id "
            f"WHERE i.id = {p}",
            (item_id,),
        ).fetchone()
    if not row or not row["title"]:
        print(f"Error: Item YOK-{item_id} not found.", file=sys.stderr)
        return result.fail(result_file, 2, "2")

    title = str(row["title"])
    old_status = str(row["status"] or "")
    worktree_field = str(row["worktree"] or "") if row["worktree"] else ""
    item_type = str(row["type"] or "issue")
    epic_name = str(item_id) if item_type == "epic" else ""
    item_project = str(row["project"] or "yoke") if row["project"] else "yoke"
    result.old_status = result.new_status = old_status
    if worktree_field in ("null", ""):
        worktree_field = ""
    if worktree_field.startswith(("issue/YOK-", "epic/YOK-")):
        print(f"Error: legacy worktree branch '{worktree_field}' is retired.", file=sys.stderr)
        print("Use the zero-legacy DB convergence tool to purge legacy "
              "worktree metadata before retrying.", file=sys.stderr)
        return result.fail(result_file, 2, "2-legacy-worktree")
    if epic_name in ("null", ""):
        epic_name = ""

    print(f"\n=== Done transition: YOK-{item_id} ===")
    print(f"Title: {title}")
    print(f"Old status: {old_status}")
    print(f"Type: {item_type}\n")
    result.add_step("2")

    project_repo, project_default_branch = _resolve_project_context(
        item_id, item_project, repo_root
    )
    if item_project != "yoke":
        print(f"Project: {item_project} (repo: {project_repo})")

    deploy_flow = _query_item_field(item_id, "deployment_flow")
    if deploy_flow in ("null", ""):
        deploy_flow = ""

    base_branch = _get_base_branch(project_default_branch, project_repo)

    if item_type == "epic":
        sim_exit = _check_simulation_gate(item_id, skip_simulation)
        if sim_exit is not None:
            return result.fail(result_file, sim_exit, "2a")
    result.add_step("2a")
    if (blocked_exit := mw._check_blocked_flag(item_id)) is not None:
        return result.fail(result_file, blocked_exit, "2a-blocked")

    branch_already_merged = _check_merge_guard(worktree_field, project_repo, base_branch)
    result.add_step("2b")

    if not branch_already_merged:
        empty_exit = _check_empty_branch(worktree_field, project_repo, base_branch, item_id)
        if empty_exit is not None:
            print(f"RESULT_FILE={result_file}")
            return result.fail(result_file, empty_exit, "2c-empty-branch")
    result.add_step("2c")

    already_done, resume_from_step6 = _check_recovery(old_status, worktree_field)

    if already_done:
        return _handle_already_done(item_id, project_repo, result, result_file)

    if resume_from_step6 and (rc := _handle_resume_from_step6(
        item_id, project_repo, base_branch, old_status, result, result_file)) is not None:
        return rc

    if not resume_from_step6:
        _pre_merge_commit(repo_root)
    result.add_step("3")

    if not resume_from_step6:
        redirect = _check_deployment_redirect(deploy_flow, skip_deploy, item_id)
        if redirect is not None:
            print(f"RESULT_FILE={result_file}")
            return result.fail(result_file, redirect, "3b")
    result.add_step("3b")

    merge_ran = False
    merge_output = ""
    if not resume_from_step6:
        if worktree_field and not branch_already_merged:
            merge_exit, merge_output, _ = _do_merge(
                item_id, worktree_field, base_branch, item_type,
                epic_name, project_repo,
            )
            if merge_exit == 0:
                merge_ran = True
            elif merge_exit in (1, 3, 4):
                if merge_exit == 1:
                    print(f"\nError: Merge of branch '{worktree_field}' failed.",
                          file=sys.stderr)
                elif merge_exit == 3:
                    print("\nMerge halted: agent resolution required.",
                          file=sys.stderr)
                elif merge_exit == 4:
                    print("\nHARD STOP: User-authored files at risk.",
                          file=sys.stderr)
                if merge_output:
                    print(merge_output, file=sys.stderr)
                print(f"RESULT_FILE={result_file}")
                return result.fail(result_file, merge_exit)
            else:
                print(f"\nError: Merge exited with unexpected code {merge_exit}.",
                      file=sys.stderr)
                if merge_output:
                    print(merge_output, file=sys.stderr)
                print(f"RESULT_FILE={result_file}")
                return result.fail(result_file, merge_exit)
        elif branch_already_merged:
            print("Branch already merged — skipping merge step.")
        else:
            if resume_from_step6:
                print("Merge already completed in prior run — continuing "
                      "with post-merge steps.")
            else:
                branch_exists = False
                verify = _run_git(
                    ["-C", str(project_repo), "rev-parse", "--verify",
                     f"YOK-{item_id}"],
                    capture=True,
                )
                if verify.returncode == 0:
                    branch_exists = True
                else:
                    ls = _run_git(
                        ["-C", str(project_repo), "ls-remote", "--heads",
                         "origin", f"YOK-{item_id}"],
                        capture=True,
                    )
                    if ls.stdout and f"YOK-{item_id}" in ls.stdout:
                        branch_exists = True
                if not branch_exists:
                    print("No worktree field and no branch found — treating "
                          "as merge already completed (crash recovery).")
                else:
                    print("No worktree field but branch exists — skipping "
                          "merge (--no-worktree was used).")

    result.add_step("4")
    if merge_ran:
        result.merge_ran = True

    cleanup_complete = _cleanup_stale_branches(
        item_id,
        worktree_field,
        project_repo,
        base_branch,
    )
    if worktree_field and cleanup_complete:
        _update_item_direct(
            item_id,
            "worktree",
            "null",
            rebuild_board=False,
            suppress_output=True,
        )
    result.add_step("4a")

    cwd = _verify_cwd_after_merge(merge_ran, merge_output, project_repo)
    if cwd is None:
        print(f"RESULT_FILE={result_file}")
        return result.fail(result_file, 2)
    result.add_step("5")

    _schema_gate(merge_ran=merge_ran, project_repo=project_repo)
    result.add_step("5a")

    deploy_guard = _check_deployment_flow_guard(
        item_id, deploy_flow, skip_deploy, item_project, old_status,
    )
    if deploy_guard is not None:
        exit_code, new_status = deploy_guard
        result.new_status = new_status
        print(f"RESULT_FILE={result_file}")
        return result.fail(result_file, exit_code, "5b")
    result.add_step("5b")

    _cross_project_commit_guard(item_id, item_project, repo_root)
    result.add_step("5c")

    if _enforce_preconditions(item_id, deploy_flow, item_type):
        print(f"RESULT_FILE={result_file}")
        return result.fail(result_file, 7, "5d-preconditions")
    result.add_step("5d")
    print("\n=== Step 6: Update status to done ===")
    _populate_merged_at(item_id)

    success = _update_status_to_done(item_id, skip_qa)
    if not success:
        verify = _query_item_field(item_id, "status")
        print(f"Error: Status update failed after retries — item is still "
              f"'{verify}'.", file=sys.stderr)
        print(
            f"Re-run `python3 -m yoke_core.engines.done_transition {item_id}` "
            "to resume from step 6.",
            file=sys.stderr,
        )
        print(f"RESULT_FILE={result_file}")
        return result.fail(result_file, 1)
    result.new_status = "done"
    result.add_step("6")
    result.add_step("6a")  # reserved result slot

    _finalize_done_local_side_effects(
        item_id, item_type, title, item_project, env_name
    )
    result.add_step("6c")

    if item_type == "epic" and epic_name:
        _cascade_epic_tasks_to_done(item_id, epic_name)
    for _s in ("6b", "6d", "7"):
        result.add_step(_s)
    print("\n=== Step 8: Sync done state to GitHub ===")
    from yoke_core.engines.done_transition_github_sync import apply_step_8
    apply_step_8(item_id, old_status, result)
    _apply_discovery_scan(item_id, result)
    for _s in ("9", "10"):
        result.add_step(_s)
    print("\n=== Step 11: Rebuild board ===")
    _rebuild_board_direct()
    result.add_step("11")

    print("\n=== Step 12: Commit ===")
    commit_ran = False
    diff = _run_git(["diff", "--cached", "--quiet"], capture=True)
    if diff.returncode != 0:
        commit = _run_git(["commit", "-m", f"YOK-{item_id}: {old_status} -> done"])
        commit_ran = commit.returncode == 0
        if commit_ran:
            from yoke_core.engines.done_transition_snapshot import (
                ensure_snapshot_for_item,
            )
            ensure_snapshot_for_item(item_id)
    result.add_step("12")

    print("\n=== Step 13: Push ===")
    if commit_ran or merge_ran:
        # Step 12's commit lands in the Yoke control-plane repo.
        push_branch = _get_base_branch("", repo_root)
        push = _run_git(["push", "origin", push_branch])
        if push.returncode != 0:
            print("Push failed - attempting rebase and retry...")
            _run_git(["pull", "--rebase", "origin", push_branch])
            retry = _run_git(["push", "origin", push_branch])
            if retry.returncode != 0:
                print("Warning: git push failed after done-transition commit. "
                      "Local is ahead of origin.")
    else:
        print("No merge commit or done-transition commit produced - skipping push.")
    result.add_step("13")

    print("\n=== Step 14: Report ===")
    print("==========================================")
    print(f"YOK-{item_id} ({title}): {old_status} -> done")
    print("==========================================\n")
    if item_type == "issue":
        print("idea -> refining-idea -> refined-idea -> implementing -> "
              "reviewing-implementation -> reviewed-implementation -> "
              "polishing-implementation -> implemented -> release -> [done]")
    else:
        print("idea -> refining-idea -> refined-idea -> planning -> "
              "plan-drafted -> refining-plan -> planned -> implementing -> "
              "reviewing-implementation -> reviewed-implementation -> "
              "polishing-implementation -> implemented -> release -> [done]")
    result.add_step("14")

    result.write(result_file)
    print(f"RESULT_FILE={result_file}")
    return 0
