"""Command surface that merges a standalone item and closes it out.

Wraps :func:`yoke_core.domain.standalone_item_merge.merge_standalone_branch`
with the item bookkeeping the merge boundary deliberately leaves to its
caller: execution evidence, GitHub sync, and the terminal lifecycle
transition, which runs the item's own workflow gates rather than bypassing
them. Reached as ``yoke merge item <ITEM>``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, List, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.standalone_item_merge import merge_standalone_branch

# Workflows whose terminal transition is gated on an execution-evidence
# record. Other standalone workflows merge through the same boundary but
# carry no evidence section.
EVIDENCE_WORKFLOWS = frozenset({"dash"})


def _fail(message: str, *, as_json: bool, **extra: Any) -> int:
    if as_json:
        print(json.dumps({"ok": False, "error": message, **extra}, indent=2))
    else:
        print(f"Error: {message}", file=sys.stderr)
    return 1


def _relay_error(response: Any, fallback: str) -> str:
    return response.error.message if response.error is not None else fallback


def _resolve_item(item_ref: str, project: Optional[str]) -> tuple[Any, str]:
    response = call_dispatcher(
        function_id="items.detail.get",
        target=TargetRef(kind="item", item_ref=item_ref, project_id=project),
        payload={},
    )
    if not response.success:
        return None, _relay_error(response, "item resolution failed")
    return (response.result or {}).get("item") or {}, ""


def _session_holds_claim(item_id: int, session_id: str) -> str:
    """Empty when this session owns the item claim, else why it does not."""
    response = call_dispatcher(
        function_id="claims.work.holder_get",
        target=TargetRef(kind="item", item_id=item_id),
    )
    if not response.success:
        return _relay_error(response, "work-claim holder lookup failed")
    holder = (response.result or {}).get("holder") or {}
    holder_session = str(holder.get("session_id") or "")
    if not holder_session:
        return (
            "no live work claim on this item; acquire one with "
            "`yoke claims work acquire`"
        )
    if session_id and holder_session != session_id:
        return f"work claim held by another session ({holder_session})"
    return ""


def _lane_branch(item: dict, item_ref: str) -> str:
    """The branch the item's implementation lane registered."""
    for lane in item.get("worktrees") or []:
        branch = str(lane.get("branch") or "").strip()
        if branch:
            return branch
    recorded = str(item.get("worktree") or "").strip()
    return recorded if recorded and recorded != "null" else item_ref


def _lane_worktree_path(item: dict) -> str:
    """The recorded path of the item's implementation lane, if any."""
    for lane in item.get("worktrees") or []:
        path = str(lane.get("path") or "").strip()
        if path:
            return path
    return ""


def _lane_commit_sha(item: dict) -> str:
    """The committed HEAD recorded by the item's implementation lane."""
    for lane in item.get("worktrees") or []:
        commit_sha = str(lane.get("commit_sha") or "").strip()
        if commit_sha:
            return commit_sha
    return ""


def _resolve_checkout(item: dict, target_override: str) -> tuple[Path, str]:
    from yoke_core.engines.done_transition_gates import (
        _get_base_branch,
        _resolve_default_branch,
        _resolve_repo_root,
    )

    project_slug = str((item.get("project") or {}).get("slug") or "yoke")
    repo_root = _resolve_repo_root()
    project_repo = repo_root
    default_branch = ""
    if project_slug != "yoke":
        from yoke_core.domain.project_checkout_locations import (
            checkout_for_project_slug,
        )

        checkout = checkout_for_project_slug(project_slug)
        if checkout is None or not Path(checkout).is_dir():
            raise RuntimeError(
                f"project '{project_slug}' has no machine-local checkout mapping"
            )
        project_repo = Path(checkout)
        if project_repo.resolve() == repo_root.resolve():
            raise RuntimeError(
                f"project '{project_slug}' maps to the Yoke checkout"
            )
        default_branch = _resolve_default_branch(project_slug)
    target = target_override or _get_base_branch(default_branch, project_repo)
    return project_repo, target or "main"


def _record_evidence(
    *,
    item_id: int,
    outcome: Any,
    result_summary: str,
    verification_summary: str,
    verification_status: str,
    no_changes: bool,
    tree_root: str,
) -> str:
    response = call_dispatcher(
        function_id="direct_workflow.dash.evidence",
        target=TargetRef(kind="item", item_id=item_id),
        payload={
            "result_summary": result_summary,
            "verification_summary": verification_summary,
            "verification_status": verification_status,
            "commit_sha": outcome.commit_sha,
            "merge_sha": outcome.merge_sha,
            "touched_files": list(outcome.touched_files),
            "no_changes": no_changes,
            # The lane's own tip is what verification covered; the merge
            # commit belongs to the base branch, not to the tree tested.
            "tree_root": tree_root,
            "tree_head_sha": outcome.commit_sha,
        },
    )
    if response.success:
        return ""
    return _relay_error(response, "evidence write failed")


def _transition_to_done(
    item_id: int,
    source_status: str,
    repo_root: Path,
    target: str,
    commit_sha: str,
) -> str:
    from yoke_core.domain import standalone_item_merge_git as git

    if not git.is_ancestor(str(repo_root), commit_sha, target):
        return (
            f"terminal transition refused: recorded merge commit {commit_sha} "
            f"is not reachable from '{target}'"
        )
    response = call_dispatcher(
        function_id="lifecycle.transition.execute",
        target=TargetRef(kind="item", item_id=item_id),
        payload={
            "source_status": source_status,
            "target_status": "done",
            "reason": "Merged and evidence recorded",
        },
    )
    if response.success:
        return ""
    return _relay_error(response, "terminal transition refused")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yoke merge item")
    parser.add_argument("item")
    parser.add_argument("--project")
    parser.add_argument(
        "--target", default="", help="Base branch override; defaults to the "
        "project's default branch.",
    )
    parser.add_argument(
        "--session-id", default=os.environ.get("YOKE_SESSION_ID", ""),
    )
    parser.add_argument("--result", default="", help="What changed or was learned.")
    parser.add_argument(
        "--verification", default="", help="Checks run and their evidence.",
    )
    parser.add_argument("--verification-status", default="passed")
    parser.add_argument(
        "--no-changes", action="store_true",
        help="Record a verified no-change result instead of touched files.",
    )
    parser.add_argument(
        "--skip-status", action="store_true",
        help="Merge and record evidence, but leave the lifecycle status alone.",
    )
    parser.add_argument(
        "--pr", action="store_true",
        help="Merge through a pull request instead of merging directly.",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def run(argv: List[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    as_json = bool(args.json)

    item, error = _resolve_item(str(args.item), args.project)
    if error:
        return _fail(f"could not resolve item {args.item!r}: {error}", as_json=as_json)

    item_id = int(item["id"])
    item_ref = str(item.get("public_ref") or args.item)
    workflow_id = str((item.get("workflow") or {}).get("id") or "")
    status = str(item.get("status") or "")
    needs_evidence = workflow_id in EVIDENCE_WORKFLOWS and not args.skip_status

    if needs_evidence and not (args.result and args.verification):
        return _fail(
            f"{item_ref} uses the {workflow_id} workflow, whose terminal "
            "transition is evidence-gated: pass --result and --verification "
            "(or --skip-status to merge without closing out).",
            as_json=as_json,
        )

    claim_error = _session_holds_claim(item_id, str(args.session_id))
    if claim_error:
        return _fail(f"{item_ref}: {claim_error}", as_json=as_json)

    try:
        repo_root, target = _resolve_checkout(item, str(args.target))
    except RuntimeError as exc:
        return _fail(f"{item_ref}: {exc}", as_json=as_json)
    branch = _lane_branch(item, item_ref)
    commit_sha = _lane_commit_sha(item)

    outcome = merge_standalone_branch(
        item_id=item_id,
        branch=branch,
        commit_sha=commit_sha,
        target=target,
        repo_root=str(repo_root),
        project=str((item.get("project") or {}).get("slug") or "yoke"),
        local_merge=not args.pr,
    )
    if not outcome.ok:
        return _fail(
            f"{item_ref}: {outcome.error}",
            as_json=as_json,
            exit_code=outcome.exit_code,
            branch=branch,
            target=target,
        )

    envelope: dict[str, Any] = {
        "ok": True,
        "item_id": item_id,
        "item_ref": item_ref,
        "branch": branch,
        "target": target,
        "already_merged": outcome.already_merged,
        "commit_sha": outcome.commit_sha,
        "merge_sha": outcome.merge_sha,
        "touched_files": list(outcome.touched_files),
        "published": outcome.pushed,
        "evidence_recorded": False,
        "status": status,
        "warnings": list(outcome.warnings),
    }

    if needs_evidence:
        evidence_error = _record_evidence(
            item_id=item_id,
            outcome=outcome,
            result_summary=str(args.result),
            verification_summary=str(args.verification),
            verification_status=str(args.verification_status),
            no_changes=bool(args.no_changes),
            tree_root=_lane_worktree_path(item) or str(repo_root),
        )
        if evidence_error:
            envelope["ok"] = False
            envelope["error"] = f"merge landed, evidence refused: {evidence_error}"
            print(json.dumps(envelope, indent=2, sort_keys=True))
            return 1
        envelope["evidence_recorded"] = True

    from yoke_core.domain.standalone_item_merge import sync_item_to_github

    sync_error = sync_item_to_github(item_id)
    if sync_error:
        envelope["warnings"].append(f"GitHub sync skipped: {sync_error}")

    if not args.skip_status:
        transition_error = _transition_to_done(
            item_id, status, repo_root, target, outcome.commit_sha,
        )
        if transition_error:
            envelope["ok"] = False
            envelope["error"] = (
                f"merge landed and evidence recorded, but the terminal "
                f"transition was refused: {transition_error}"
            )
            print(json.dumps(envelope, indent=2, sort_keys=True))
            return 1
        envelope["status"] = "done"

    print(json.dumps(envelope, indent=2, sort_keys=True))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    return run(list(sys.argv[1:] if argv is None else argv))


__all__ = ["EVIDENCE_WORKFLOWS", "main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
