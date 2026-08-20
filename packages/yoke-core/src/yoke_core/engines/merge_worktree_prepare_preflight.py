"""Preflight checks for merge-worktree preparation."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from typing import TYPE_CHECKING

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.classify_dirty_files import is_yoke_managed_pattern
from yoke_core.domain.project_identity_item_ref import item_ref_for_id

if TYPE_CHECKING:  # the cycle-free half of the prepare<->preflight pair
    from yoke_core.engines.merge_worktree_prepare import MergeContext

# merge_worktree_prepare re-exports preflight_checks at module bottom, so a
# module-top import back into it is order-dependent (whichever module loads
# first wins; the loser sees a partially initialized module). Runtime helpers
# import lazily inside the functions that use them.


def _parent():
    from yoke_core.engines import merge_worktree as _mw
    return _mw

def preflight_checks(ctx: MergeContext) -> Optional[Tuple[int, str]]:
    """Run preflight checks. Returns (exit_code, message) on failure, None on success."""
    mw = _parent()
    _print = mw._print
    _run_git = mw._run_git

    _print("Running pre-flight checks...")
    fail = False
    exit_code = 1

    # PF-1: Worktree cleanliness
    dirty_tracked = _run_git(["diff", "--name-only"], cwd=ctx.worktree_path, capture=True)
    dirty_untracked = _run_git(
        ["ls-files", "--others", "--exclude-standard"], cwd=ctx.worktree_path, capture=True
    )
    # The index is a third source of dirt and the only one that survives
    # having no working-tree counterpart: a staged deletion shows up in
    # neither of the two probes above, so without this the merge would
    # report a clean worktree and then carry the deletion into the merge
    # commit. A second process sharing this worktree can stage entries
    # this one never made.
    dirty_staged = _run_git(
        ["diff", "--cached", "--name-only"], cwd=ctx.worktree_path, capture=True
    )

    all_dirty = []
    if dirty_tracked.stdout.strip():
        all_dirty.extend(dirty_tracked.stdout.strip().splitlines())
    if dirty_untracked.stdout.strip():
        all_dirty.extend(dirty_untracked.stdout.strip().splitlines())
    if dirty_staged.stdout.strip():
        all_dirty.extend(dirty_staged.stdout.strip().splitlines())
    all_dirty = list(dict.fromkeys(all_dirty))

    yoke_dirty = [f for f in all_dirty if is_yoke_managed_pattern(f)]
    user_dirty = [f for f in all_dirty if not is_yoke_managed_pattern(f)]

    # Auto-commit Yoke-managed files
    if yoke_dirty:
        _print("  Auto-committing Yoke-managed files in worktree...", err=True)
        for sf in yoke_dirty:
            _run_git(["add", sf], cwd=ctx.worktree_path)
        _run_git(
            ["commit", "-m", f"chore: auto-commit Yoke-managed files before merge [{ctx.args.branch}]"],
            cwd=ctx.worktree_path, capture=True,
        )

    if user_dirty:
        _print("  FAIL: Uncommitted non-Yoke files in worktree:", err=True)
        for uf in user_dirty:
            _print(f"    - {uf}", err=True)
        exit_code = 4
        fail = True
    else:
        _print("  OK: Worktree clean (no uncommitted non-Yoke files)")

    # PF-2: Branch tracking
    local_head = _run_git(["rev-parse", "HEAD"], cwd=ctx.worktree_path, capture=True)
    remote_head = _run_git(
        ["rev-parse", f"origin/{ctx.args.branch}"], cwd=ctx.worktree_path, capture=True
    )
    if local_head.returncode == 0 and remote_head.returncode == 0:
        behind = _run_git(
            ["rev-list", f"HEAD..origin/{ctx.args.branch}", "--count"],
            cwd=ctx.worktree_path, capture=True,
        )
        behind_count = int(behind.stdout.strip()) if behind.returncode == 0 else 0
        if behind_count > 0:
            _print(f"  FAIL: Worktree branch is {behind_count} commit(s) behind origin/{ctx.args.branch}", err=True)
            fail = True
        else:
            _print(f"  OK: Branch up to date with origin/{ctx.args.branch}")
    else:
        _print("  OK: Branch tracking check skipped (no remote tracking branch)")

    # PF-3: Epic tasks (when epic ID provided). The completeness verdict runs
    # on the relayed epic-task status survey so it evaluates over an https
    # control plane as well as a local Postgres connection; the terminal
    # success set stays engine-owned.
    if ctx.epic_id:
        from yoke_core.engines.merge_worktree_prepare import _TASK_TERMINAL_SUCCESS

        try:
            resp = call_dispatcher(
                function_id="merge.preflight.epic_task_statuses",
                target=TargetRef(kind="item", item_id=int(ctx.epic_id)),
                payload={},
            )
            if resp.success:
                tasks = (resp.result or {}).get("tasks") or []
                incomplete = [
                    t for t in tasks
                    if t.get("status") not in _TASK_TERMINAL_SUCCESS
                ]
                if tasks and incomplete:
                    _print("  FAIL: Incomplete tasks found:", err=True)
                    for row in incomplete:
                        _print(
                            f"    - {row['task_num']}:{row['status']}", err=True
                        )
                    fail = True
                elif tasks:
                    _print("  OK: All tasks completed")
        except Exception:  # noqa: BLE001 - preflight degrades if the read is unavailable.
            pass

    # PF-4: Integration simulation gate (epics only). The relayed read
    # replaces the local ``db_router`` child process so the gate runs over an
    # https control plane; a missing report (or a refused relay) stays a hard
    # block unless --skip-simulation is set, matching the child-process path.
    if ctx.epic_id:
        found = False
        try:
            resp = call_dispatcher(
                function_id="workflow_item.epic_task.simulation_get",
                target=TargetRef(kind="epic_task", epic_id=int(ctx.epic_id)),
                payload={"phase": "integration"},
            )
            found = resp.success and bool(
                str((resp.result or {}).get("body") or "").strip()
            )
        except Exception:  # noqa: BLE001 - a refused relay reads as "report not found".
            found = False
        if not found:
            if ctx.args.skip_simulation:
                _print(f"  WARN: Integration simulation gate overridden (--skip-simulation) for epic: {ctx.epic_id}", err=True)
            else:
                _print(f"  FAIL: Integration simulation report not found for epic: {ctx.epic_id}", err=True)
                _print("    Run /yoke simulate first, or pass --skip-simulation to override.", err=True)
                fail = True
        else:
            _print("  OK: Canonical integration simulation report exists")

    # PF-5: Integration dependency gate. The relayed evaluation replaces the
    # local ``service_client`` child process so the gate runs over an https
    # control plane. Item-bound merges use typed identity and fail closed when
    # the gate cannot evaluate; generic branch merges retain the advisory
    # fallback.
    try:
        dep_target = (
            TargetRef(kind="item", item_id=int(ctx.item_id))
            if ctx.item_id is not None
            else TargetRef(kind="global")
        )
        dep_payload = {"gate_point": "integration"}
        if ctx.item_id is None:
            dep_payload["item_ref"] = ctx.args.branch
        dep_resp = call_dispatcher(
            function_id="merge.preflight.dependency_gate",
            target=dep_target,
            payload=dep_payload,
        )
    except Exception:  # noqa: BLE001 - classified below by item authority.
        dep_resp = None
    if dep_resp is not None and dep_resp.success:
        gate_data = dep_resp.result or {}
        if gate_data.get("is_blocked"):
            _print(f"  FAIL: Integration dependency gate blocked for {ctx.args.branch}", err=True)
            for b in gate_data.get("unsatisfied_blockers", []):
                _print(
                    f"    - {b.get('blocking_item', '?')} ({b.get('blocking_status', '?')}): "
                    f"{b.get('rationale', 'no rationale')}",
                    err=True,
                )
            fail = True
        else:
            _print("  OK: Integration dependency gate clear")
    else:
        if ctx.item_id is not None:
            _print(
                "  FAIL: Integration dependency gate unavailable for "
                f"item {ctx.item_id}",
                err=True,
            )
            fail = True
        else:
            _print(
                "  OK: Integration dependency gate skipped "
                "(dependency read unavailable)"
            )

    # PF-6: blocked-flag refusal. The relayed read resolves the active
    # worktree lane for the branch and reads the item's blocked flag so the
    # gate runs over an https control plane; it only fires when a lane exists
    # (matching the local query) and degrades to a skip when unavailable. The
    # public item ref is rendered server-side in the relay handler so the
    # block narrative matches the local-connection path over https as well.
    try:
        resp = call_dispatcher(
            function_id="merge.preflight.blocked_gate",
            target=TargetRef(kind="global"),
            payload={"branch": ctx.args.branch},
        )
        if resp.success:
            data = resp.result or {}
            if data.get("applicable"):
                iid = int(data.get("item_id"))
                ref = data.get("item_ref") or item_ref_for_id(iid)
                if data.get("blocked"):
                    _print(f"  FAIL: Item {ref} is blocked (items.blocked=1).", err=True)
                    if data.get("reason"):
                        _print(f"    Reason: {data['reason']}", err=True)
                    _print(
                        f"    Run yoke items unblock {ref} before merging.",
                        err=True,
                    )
                    fail = True
                else:
                    _print("  OK: Item not blocked")
        else:
            _print("  OK: Blocked-flag gate skipped (DB unavailable)")
    except Exception:  # noqa: BLE001 - degrade if DB unavailable
        _print("  OK: Blocked-flag gate skipped (DB unavailable)")

    # PF-7: Numbered migration history integrity. The existing item-list and
    # capability-settings reads keep this gate deployable across an HTTPS
    # control plane: the server provides state, while the merge host proves
    # the lane-vs-target Git ordering from its own checkout.
    if ctx.item_id is not None:
        from yoke_core.domain.migration_merge_preflight import (
            evaluate_migration_merge,
            migration_merge_applicable,
        )

        project = ctx.project or "yoke"
        try:
            items_resp = call_dispatcher(
                function_id="items.list.run",
                target=TargetRef(kind="global"),
                payload={
                    "project": project,
                    "fields": ["id", "status", "db_mutation_profile"],
                },
            )
        except Exception:  # noqa: BLE001 - item-bound gate fails closed below.
            items_resp = None
        if items_resp is None or not items_resp.success:
            _print(
                "  FAIL: Migration-history item roster unavailable for "
                f"item {ctx.item_id}",
                err=True,
            )
            fail = True
        else:
            rows = list((items_resp.result or {}).get("rows") or [])
            if not migration_merge_applicable(rows, int(ctx.item_id)):
                _print("  OK: Numbered migration-history gate not applicable")
            else:
                try:
                    capability_resp = call_dispatcher(
                        function_id="projects.capability_settings.get",
                        target=TargetRef(kind="global"),
                        payload={
                            "project": project,
                            "cap_type": "migration_model",
                        },
                    )
                except Exception:  # noqa: BLE001 - fail closed below.
                    capability_resp = None
                if capability_resp is None or not capability_resp.success:
                    _print(
                        "  FAIL: migration_model capability settings unavailable "
                        f"for project {project!r}",
                        err=True,
                    )
                    fail = True
                else:
                    decision = evaluate_migration_merge(
                        rows=rows,
                        item_id=int(ctx.item_id),
                        capability_settings_json=str(
                            (capability_resp.result or {}).get("settings_json") or ""
                        ),
                        worktree_path=Path(ctx.worktree_path),
                        integration_target=ctx.args.target,
                    )
                    if decision.passed:
                        _print("  OK: Numbered migration history extends target")
                    else:
                        _print("  FAIL: Numbered migration-history gate refused:", err=True)
                        for error in decision.errors:
                            _print(f"    - {error}", err=True)
                        fail = True

    if fail:
        _print("", err=True)
        _print("Pre-flight failed. Fix the issues above before merging.", err=True)
        return (exit_code, "preflight failed")

    _print("Pre-flight checks passed.")
    _print("")
    return None
