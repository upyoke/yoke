"""Done-transition pre-merge and deployment gate facade."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Tuple

from yoke_core.domain.qa_gates import check_epic_simulation_gate
from yoke_core.domain.worktree import resolve_main_root


def _parent():
    from yoke_core.engines import done_transition as _dt
    return _dt

def _resolve_repo_root() -> Path:
    """Enforce repo-root CWD using the Python path resolver."""
    try:
        root = resolve_main_root()
    except RuntimeError:
        root = ""
    if not root or not Path(root).is_dir():
        print("Error: Cannot determine repo root — path resolution failed.", file=sys.stderr)
        return Path()
    return Path(root)


def _resolve_project_context(
    item_id: int, item_project: str, repo_root: Path
) -> Tuple[Path, str]:
    """Resolve project checkout and default branch."""
    from yoke_core.domain import projects as _projects

    project_repo = repo_root
    default_branch = ""
    if item_project and item_project != "yoke":
        db_path = None
        try:
            from yoke_core.domain.db_helpers import connect
            from yoke_core.domain.project_checkout_locations import checkout_for_project

            with connect(db_path) as conn:
                checkout = checkout_for_project(conn, item_project)
            if checkout is not None and Path(checkout).is_dir():
                project_repo = Path(checkout)
        except Exception:
            pass
        db_val = (_projects.cmd_get(item_project, field="default_branch", db_path=db_path) or "").strip()
        if db_val and db_val != "null":
            default_branch = db_val
    return project_repo, default_branch


def _get_base_branch(default_branch: str, repo_root: "Path | None" = None) -> str:
    """Get base branch: project DB default, else the repo's scope-first read."""
    if default_branch:
        return default_branch
    from yoke_core.domain import project_settings

    return project_settings.get_project_str(repo_root, "base_branch")


def _check_simulation_gate(item_id: int, skip: bool) -> Optional[int]:
    """Check integration simulation gate for epics. Returns exit code or None."""
    if skip:
        print("WARNING: Integration simulation gate bypassed via --skip-simulation "
              f"for YOK-{item_id}")
        return None

    gate = check_epic_simulation_gate(item_id, None)
    if gate.passed:
        return None
    gate.emit_errors()
    return 3


def _check_merge_guard(
    worktree_field: str,
    project_repo: Path,
    base_branch: str,
) -> bool:
    """Check if branch is already merged. Returns True if already merged.

    Ancestry and squash-merge signals are evaluated against
    ``origin/{base_branch}`` after a fetch, not the local base ref. A local
    base can lead origin (e.g., a prior rebase tip-matched the branch),
    which would otherwise false-positive and cause done-transition to skip a
    merge that hasn't landed yet — the operator then has to recover the
    worktree and rerun the merge engine. Mirrors merge_worktree_runner's
    own already-merged guard.
    """
    if not worktree_field:
        return False
    # Branch missing locally — assume already merged and cleaned up.
    verify = _parent()._run_git(
        ["-C", str(project_repo), "rev-parse", "--verify", worktree_field],
        capture=True,
    )
    if verify.returncode != 0:
        print(f"Merge guard: branch '{worktree_field}' not found locally "
              "(likely already merged and cleaned up) — skipping merge step.")
        return True
    # Fetch origin so ancestry/squash signals reflect production state.
    _parent()._run_git(
        ["-C", str(project_repo), "fetch", "origin", base_branch],
        capture=True,
    )
    target_ref = f"origin/{base_branch}"
    origin_check = _parent()._run_git(
        ["-C", str(project_repo), "rev-parse", "--verify", target_ref],
        capture=True,
    )
    if origin_check.returncode != 0:
        # No origin ref available (e.g., test env without remote) — fall
        # back to local base. Better than no check at all.
        target_ref = base_branch
    ancestry = _parent()._run_git(
        ["-C", str(project_repo), "merge-base", "--is-ancestor",
         worktree_field, target_ref],
        capture=True,
    )
    if ancestry.returncode == 0:
        print(f"Merge guard: branch '{worktree_field}' is merged to "
              f"{target_ref} — skipping merge step.")
        return True
    log_check = _parent()._run_git(
        ["-C", str(project_repo), "log", "--oneline",
         f"--grep={worktree_field}", target_ref],
        capture=True,
    )
    first_line = (log_check.stdout or "").strip().split("\n")[0] if log_check.stdout else ""
    if first_line:
        print(f"Merge guard: squash-merge detected for branch '{worktree_field}' "
              f"on {target_ref} — skipping merge step.")
        return True
    print(f"Merge guard: branch '{worktree_field}' not yet merged to "
          f"{target_ref} — Step 4 will merge.")
    return False


def _verify_recovery_evidence(
    item_id: int,
    project_repo: Path,
    base_branch: str,
) -> bool:
    """Defense-in-depth for _check_recovery's resume_from_step6 path.

    "no worktree + status != done" can mean either (a) a prior run completed
    the merge but did not reach the status update — legitimate resume — or
    (b) a false-positive guard cleared the worktree field without an actual
    merge. (a) leaves a squash-merge commit referencing YOK-N on
    origin/{base_branch}; (b) does not. Returning False refuses the
    fraudulent recovery and forces the operator to restore worktree state
    explicitly.
    """
    _parent()._run_git(
        ["-C", str(project_repo), "fetch", "origin", base_branch],
        capture=True,
    )
    target_ref = f"origin/{base_branch}"
    origin_check = _parent()._run_git(
        ["-C", str(project_repo), "rev-parse", "--verify", target_ref],
        capture=True,
    )
    if origin_check.returncode != 0:
        target_ref = base_branch
    log_check = _parent()._run_git(
        ["-C", str(project_repo), "log", "--oneline",
         f"--grep=YOK-{item_id}", target_ref],
        capture=True,
    )
    return bool((log_check.stdout or "").strip())


def _handle_resume_from_step6(
    item_id: int,
    project_repo: Path,
    base_branch: str,
    old_status: str,
    result,
    result_file: str,
) -> Optional[int]:
    """Verify recovery evidence and emit pre-flight messages, or fail.

    Returns None when evidence is present (caller proceeds to step 6).
    Returns a TransitionResult.fail() exit code when evidence is absent
    (caller returns it immediately). All user-facing output is emitted
    here so the runner stays a compact dispatcher.
    """
    if not _verify_recovery_evidence(item_id, project_repo, base_branch):
        print(
            f"\nError: YOK-{item_id} has no worktree field but no merge "
            f"evidence found on origin/{base_branch}.\n"
            "State is inconsistent — refusing to skip merge step.\n"
            "If the branch was merged out-of-band, push the merge commit "
            "to origin and retry. Otherwise restore the worktree field:\n"
            f"  python3 -m yoke_core.cli.db_router items "
            f"update YOK-{item_id} worktree <branch-name>",
            file=sys.stderr,
        )
        print(f"RESULT_FILE={result_file}")
        return result.fail(result_file, 2, "2d-recovery-no-evidence")
    print(
        f"Pre-flight: merge already completed (no worktree), status is "
        f"'{old_status}'."
    )
    print("Resuming from step 6 (status update and post-merge steps).")
    return None


def _check_empty_branch(
    worktree_field: str,
    project_repo: Path,
    base_branch: str,
    item_id: int,
) -> Optional[int]:
    """Check for empty worktree branch. Returns exit code or None."""
    if not worktree_field:
        return None
    verify = _parent()._run_git(
        ["-C", str(project_repo), "rev-parse", "--verify", worktree_field],
        capture=True,
    )
    if verify.returncode != 0:
        return None
    count_result = _parent()._run_git(
        ["-C", str(project_repo), "rev-list", "--count",
         f"{base_branch}..{worktree_field}"],
        capture=True,
    )
    count = int((count_result.stdout or "0").strip() or "0")
    if count == 0:
        print("", file=sys.stderr)
        print("=== Empty worktree branch guard ===", file=sys.stderr)
        print(f"Blocked: Branch '{worktree_field}' has no commits beyond "
              f"'{base_branch}'.", file=sys.stderr)
        print("No implementation work was done — cannot transition to done.",
              file=sys.stderr)
        print("", file=sys.stderr)
        print("Either:", file=sys.stderr)
        print("  - Implement the item's acceptance criteria in the worktree, "
              "then retry", file=sys.stderr)
        print("  - If this item is intentionally evidence-only, clear the "
              "worktree field and retry:", file=sys.stderr)
        print(f"      yoke items scalar update YOK-{item_id} "
              f"--field worktree --null", file=sys.stderr)
        print("    Future evidence-only items should enter implementing with "
              f"/yoke advance YOK-{item_id} implementing --no-worktree.",
              file=sys.stderr)
        return 8
    return None


def _check_recovery(
    old_status: str, worktree_field: str
) -> Tuple[bool, bool]:
    """Detect recovery state. Returns (already_done, resume_from_step6)."""
    if old_status == "done" and not worktree_field:
        return True, False
    if old_status != "done" and not worktree_field:
        return False, True
    return False, False


def _check_blocked_flag(item_id: int) -> Optional[int]:
    """refuse done-transition while items.blocked=1.

    Returns exit code 9 when the flag is set, None when clear or when
    the DB is unavailable. The done-cleanup mutation logic clears blocked
    automatically when status flips to done — this gate ensures the flip
    cannot happen while the flag is still set, so the operator sees an
    explicit refusal instead of having the cleanup silently swallow it.
    """
    try:
        from yoke_core.domain.advance_blocked_gate import evaluate as _eval
        conn = _parent()._connect()
        try:
            decision = _eval(conn, item_id)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - degrade if DB unavailable
        return None
    if not decision.blocked:
        return None
    print(
        f"\n=== Blocked-flag refusal ===\n"
        f"Item YOK-{item_id} has items.blocked=1; cannot transition to done.\n"
        + (f"Reason: {decision.reason}\n" if decision.reason else "")
        + f"Run /yoke unblock YOK-{item_id} first."
    )
    return 9


def _check_deployment_redirect(deploy_flow: str, skip_deploy: bool, item_id: int) -> Optional[int]:
    """Pre-merge deployment flow redirect. Returns exit code or None."""
    is_internal = deploy_flow.endswith("-internal") if deploy_flow else False
    if deploy_flow and not is_internal and not skip_deploy:
        print(f"\n=== Deployment flow redirect ===")
        print(f"Item YOK-{item_id} has deployment flow '{deploy_flow}'.")
        print(f"Use '/yoke usher YOK-{item_id}' to merge and deploy through the pipeline.")
        print(f"If deployment was handled out-of-band, use "
              f"'/yoke advance YOK-{item_id} done --skip-deploy'.")
        return 7
    return None

from yoke_core.engines.done_transition_deploy_gates import (  # noqa: E402,F401
    _check_deployment_flow_guard,
    _check_deployment_evidence,
    _get_latest_run_status,
    _check_run_stage_consistency,
    _check_run_qa_gates,
    _cascade_release_to_children,
)
