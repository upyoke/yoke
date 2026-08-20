"""Done-transition pre-merge and deployment gate facade."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Tuple

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.item_ref import format_item_ref
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.qa_gates import check_epic_simulation_gate
from yoke_core.domain.worktree import resolve_main_root
from yoke_core.engines.done_transition_merge_guards import (  # noqa: F401
    _check_merge_guard,
    _handle_resume_from_step6,
    _verify_recovery_evidence,
)


def _parent():
    from yoke_core.engines import done_transition as _dt

    return _dt


def _ref(item_id: int, item_ref: Optional[str] = None) -> str:
    """Best-effort public ref for operator-facing gate messages.

    ``item_ref`` is preferred when the runner already resolved it over the
    transport. The local lookup remains a compatibility path for direct
    callers and tests.
    Falls back to the default-prefix form when the control-plane DB cannot
    be reached, so a gate refusal never fails on the ref render.
    """
    if item_ref:
        return item_ref
    try:
        from yoke_core.domain.db_helpers import connect
        from yoke_core.domain.project_identity import render_item_ref

        with connect() as conn:
            return render_item_ref(conn, item_id)
    except Exception:
        return format_item_ref(None, None, None, item_id=item_id)


def _resolve_repo_root() -> Path:
    """Enforce repo-root CWD using the Python path resolver."""
    try:
        root = resolve_main_root()
    except RuntimeError:
        root = ""
    if not root or not Path(root).is_dir():
        print(
            "Error: Cannot determine repo root — path resolution failed.",
            file=sys.stderr,
        )
        return Path()
    return Path(root)


def _resolve_default_branch(project: str) -> str:
    """Relay the project's ``default_branch`` (empty when unset/unavailable).

    Project context is best-effort: a refused relay or transport error
    yields an empty default branch, and the base-branch fallback fills in
    downstream — matching the old ``cmd_get(...) or ""`` treatment.
    """
    try:
        resp = call_dispatcher(
            function_id="projects.get",
            target=TargetRef(kind="global"),
            payload={"project": project, "field": "default_branch"},
        )
    except Exception:  # noqa: BLE001 - project context is best-effort.
        return ""
    if not resp.success:
        return ""
    value = str((resp.result or {}).get("value") or "").strip()
    return "" if value == "null" else value


def _resolve_project_context(
    item_id: int, item_project: str, repo_root: Path
) -> Tuple[Path, str]:
    """Resolve project checkout and default branch.

    The checkout mapping and default-branch reads route through the
    transport-aware relay so a non-yoke project's context resolves over an
    https control plane; the machine-local checkout mapping itself stays
    local. Project context is best-effort — a failed read leaves the main
    checkout and an empty default branch.
    """
    project_repo = repo_root
    default_branch = ""
    if item_project and item_project != "yoke":
        try:
            from yoke_core.domain.project_checkout_locations import (
                checkout_for_project_slug,
            )

            checkout = checkout_for_project_slug(item_project)
            if checkout is not None and Path(checkout).is_dir():
                project_repo = Path(checkout)
        except Exception:  # noqa: BLE001 - default main checkout is safe.
            pass
        default_branch = _resolve_default_branch(item_project)
    return project_repo, default_branch


def _get_base_branch(default_branch: str, repo_root: "Path | None" = None) -> str:
    """Get base branch: project DB default, else the repo's scope-first read."""
    if default_branch:
        return default_branch
    from yoke_core.domain import project_settings

    return project_settings.get_project_str(repo_root, "base_branch")


def _check_simulation_gate(
    item_id: int, skip: bool, *, item_ref: Optional[str] = None
) -> Optional[int]:
    """Check integration simulation gate for epics. Returns exit code or None."""
    if skip:
        print(
            "WARNING: Integration simulation gate bypassed via --skip-simulation "
            f"for {_ref(item_id, item_ref)}"
        )
        return None

    gate = check_epic_simulation_gate(item_id, None)
    if gate.passed:
        return None
    gate.emit_errors()
    return 3


def _check_empty_branch(
    lane_branch: str,
    project_repo: Path,
    base_branch: str,
    item_id: int,
    *,
    item_ref: Optional[str] = None,
) -> Optional[int]:
    """Check for empty worktree branch. Returns exit code or None."""
    if not lane_branch:
        return None
    verify = _parent()._run_git(
        ["-C", str(project_repo), "rev-parse", "--verify", lane_branch],
        capture=True,
    )
    if verify.returncode != 0:
        return None
    count_result = _parent()._run_git(
        [
            "-C",
            str(project_repo),
            "rev-list",
            "--count",
            f"{base_branch}..{lane_branch}",
        ],
        capture=True,
    )
    count = int((count_result.stdout or "0").strip() or "0")
    if count == 0:
        print("", file=sys.stderr)
        print("=== Empty worktree branch guard ===", file=sys.stderr)
        print(
            f"Blocked: Branch '{lane_branch}' has no commits beyond '{base_branch}'.",
            file=sys.stderr,
        )
        print(
            "No implementation work was done — cannot transition to done.",
            file=sys.stderr,
        )
        print("", file=sys.stderr)
        print("Either:", file=sys.stderr)
        print(
            "  - Implement the item's acceptance criteria in the worktree, then retry",
            file=sys.stderr,
        )
        print(
            "  - If this item is intentionally evidence-only, release the "
            "active lane and retry through the workflow's no-worktree "
            "entry path.",
            file=sys.stderr,
        )
        print(
            "    Future evidence-only items should enter implementing with "
            f"/yoke advance {_ref(item_id, item_ref)} implementing --no-worktree.",
            file=sys.stderr,
        )
        return 8
    return None


def _check_recovery(old_status: str, lane_branch: str) -> Tuple[bool, bool]:
    """Detect recovery state. Returns (already_done, resume_from_step6)."""
    if old_status == "done" and not lane_branch:
        return True, False
    return False, False


def _check_blocked_flag(
    item_id: int, *, item_ref: Optional[str] = None
) -> Optional[int]:
    """refuse done-transition while items.blocked=1.

    Returns exit code 9 when the flag is set, None when clear or when
    the DB is unavailable. The done-cleanup mutation logic clears blocked
    automatically when status flips to done — this gate ensures the flip
    cannot happen while the flag is still set, so the operator sees an
    explicit refusal instead of having the cleanup silently swallow it.

    The blocked read routes through the transport-aware
    ``done_transition.blocked_gate`` relay so it runs over an https control
    plane as well as a local Postgres connection; it degrades to a skip
    (``None``) when the read is unavailable, preserving the advisory
    ``except: return None`` behavior.
    """
    try:
        resp = call_dispatcher(
            function_id="done_transition.blocked_gate",
            target=TargetRef(kind="item", item_id=int(item_id)),
            payload={},
        )
    except Exception:  # noqa: BLE001 - degrade if the read is unavailable
        return None
    if not resp.success:
        return None
    data = resp.result or {}
    if not data.get("blocked"):
        return None
    reason = data.get("reason")
    ref = _ref(item_id, item_ref)
    print(
        f"\n=== Blocked-flag refusal ===\n"
        f"Item {ref} has items.blocked=1; cannot transition to done.\n"
        + (f"Reason: {reason}\n" if reason else "")
        + f"Run yoke items unblock {ref} first."
    )
    return 9


def _check_deployment_redirect(
    deploy_flow: str,
    skip_deploy: bool,
    item_id: int,
    *,
    item_ref: Optional[str] = None,
) -> Optional[int]:
    """Pre-merge deployment flow redirect. Returns exit code or None."""
    is_internal = deploy_flow.endswith("-internal") if deploy_flow else False
    if deploy_flow and not is_internal and not skip_deploy:
        ref = _ref(item_id, item_ref)
        print("\n=== Deployment flow redirect ===")
        print(f"Item {ref} has deployment flow '{deploy_flow}'.")
        print(
            f"Use '/yoke usher {ref}' to merge and deploy through the pipeline."
        )
        print(
            f"If deployment was handled out-of-band, use "
            f"'/yoke advance {ref} done --skip-deploy'."
        )
        return 7
    return None


from yoke_core.engines.done_transition_deploy_gates import (  # noqa: E402,F401
    _check_deployment_flow_guard,
    _check_deployment_evidence,
    _get_latest_run_status,
    _check_run_stage_consistency,
    _check_run_qa_gates,
)
