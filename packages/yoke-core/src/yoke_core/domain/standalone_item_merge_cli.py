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
from yoke_core.domain.merge_preflight_github_lock_retry import (
    call_with_machine_lock_retry,
)
from yoke_core.domain import merge_queue_landing_timeout as _timeout
from yoke_core.domain import standalone_item_merge_evidence as evidence
from yoke_core.domain import standalone_item_merge_recovery as recovery
from yoke_core.domain.merge_queue_route_selection import (
    route_standalone_landing,
)
from yoke_core.domain.session_liveness_pump import SessionLivenessPump
from yoke_core.domain.standalone_item_merge_checkout import (
    ensure_usable_cwd as _ensure_usable_cwd,
    resolve_checkout as _resolve_checkout,
)
from yoke_core.domain.standalone_item_merge_lane import (
    active_lanes,
    lane_branch,
    lane_path,
    lane_resolution_error,
)
from yoke_core.domain.standalone_item_merge_qa import preflight as qa_preflight
from yoke_core.domain.terminal_lane_cleanup import cleanup_terminal_item_lanes
from yoke_contracts.dash_evidence_status import status_argument_kwargs

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
    response = call_with_machine_lock_retry(
        lambda: call_dispatcher(
            function_id="items.detail.get",
            target=TargetRef(kind="item", item_ref=item_ref, project_id=project),
            payload={},
        )
    )
    if not response.success:
        return None, _relay_error(response, "item resolution failed")
    return (response.result or {}).get("item") or {}, ""


def _session_holds_claim(item_id: int, session_id: str) -> str:
    """Empty when this session owns the item claim, else why it does not."""
    return recovery.claim_error(item_id, session_id)


def _announce_close_out(step: str) -> None:
    """Name each close-out step so a killed capture shows where it stopped."""
    print(f"[phase:close-out] {step}", file=sys.stderr, flush=True)


def _transition_to_done(
    item_id: int,
    source_status: str,
    repo_root: Path,
    target: str,
    commit_sha: str,
    merge_sha: str = "",
) -> str:
    from yoke_core.domain import standalone_item_merge_git as git

    # Either identity proves the landing: a queue or squash merge can rewrite
    # the lane head, leaving only the merge commit reachable from the target.
    landed = any(
        git.is_landed(str(repo_root), sha, target)
        for sha in (commit_sha, merge_sha) if sha
    )
    if not landed:
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
    parser.add_argument("--verification-status", **status_argument_kwargs())
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

    lane_error = lane_resolution_error(item)
    if active_lanes(item) and lane_error:
        return _fail(
            f"{item_ref}: {lane_error}", as_json=as_json,
        )

    branch = lane_branch(item, item_ref)
    claim_error = _session_holds_claim(item_id, str(args.session_id))
    if claim_error:
        # A claim released by a close-out that already completed is not a
        # refusal to report; the item's own record says the work landed.
        closed_out = evidence.closed_out_envelope(
            item, item_ref=item_ref, branch=branch, claim_note=claim_error,
        )
        if closed_out is not None:
            print(json.dumps(closed_out, indent=2, sort_keys=True))
            return 0
        if not recovery.claim_is_missing(claim_error):
            return _fail(f"{item_ref}: {claim_error}", as_json=as_json)

    try:
        repo_root, target = _resolve_checkout(item, str(args.target))
    except RuntimeError as exc:
        return _fail(f"{item_ref}: {exc}", as_json=as_json)
    _ensure_usable_cwd(repo_root, lane_path(item))
    pruned_lane = (
        not active_lanes(item) and recovery.branch_needs_receipt(
            str(repo_root), branch,
        )
    )
    if claim_error or pruned_lane:
        receipt, recovery_error = recovery.reacquire_landed_claim(
            item_id=item_id,
            branch=branch,
            target=target,
            repo_root=str(repo_root),
            project=str((item.get("project") or {}).get("slug") or "yoke"),
            session_id=str(args.session_id),
        )
        if recovery_error or receipt is None:
            return _fail(
                f"{item_ref}: {recovery_error or 'claim recovery failed'}",
                as_json=as_json,
            )
        item = recovery.with_recorded_head(item, receipt)
    commit_sha, qa_error = qa_preflight(
        item, item_ref=item_ref, repo_root=repo_root, branch=branch,
    )
    if qa_error:
        return _fail(f"{item_ref}: {qa_error}", as_json=as_json)

    outcome = route_standalone_landing(
        item_id=item_id,
        branch=branch,
        commit_sha=commit_sha,
        target=target,
        repo_root=str(repo_root),
        project=str((item.get("project") or {}).get("slug") or "yoke"),
        item_ref=item_ref,
        local_merge=not args.pr,
        resume_command=_timeout.merge_item_resume_command(item_ref, args),
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
        _announce_close_out("recording evidence")
        write_error = evidence.record(
            item_id=item_id,
            outcome=outcome,
            result_summary=str(args.result),
            verification_summary=str(args.verification),
            verification_status=str(args.verification_status),
            no_changes=bool(args.no_changes),
            tree_root=lane_path(item) or str(repo_root),
        )
        # A refused attempt may still have landed the row — a relayed write
        # that succeeds on retry reports the failed try. The record's own
        # state answers for this merge, not the attempt's return.
        if write_error and not evidence.recorded_covers_merge(
            item_id, outcome.merge_sha,
        ):
            envelope["ok"] = False
            envelope["error"] = f"merge landed, evidence refused: {write_error}"
            print(json.dumps(envelope, indent=2, sort_keys=True))
            return 1
        if write_error:
            envelope["warnings"].append(
                f"evidence write reported '{write_error}', but the record "
                "covers this merge; close-out continued"
            )
        envelope["evidence_recorded"] = True

    from yoke_core.domain.standalone_item_merge import sync_item_to_github

    _announce_close_out("syncing GitHub")
    sync_error = sync_item_to_github(item_id)
    if sync_error:
        envelope["warnings"].append(f"GitHub sync skipped: {sync_error}")

    if not args.skip_status:
        _announce_close_out("terminal transition")
        transition_error = _transition_to_done(
            item_id, status, repo_root, target, outcome.commit_sha,
            outcome.merge_sha,
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
        _announce_close_out("lane cleanup")
        envelope["warnings"].extend(cleanup_terminal_item_lanes(
            {**item, "claim": None}, target_status="done",
            session_id=str(args.session_id),
            repo_root=repo_root, target_branch=target,
        ))

    print(json.dumps(envelope, indent=2, sort_keys=True))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    with SessionLivenessPump().running():
        return run(list(sys.argv[1:] if argv is None else argv))


__all__ = ["EVIDENCE_WORKFLOWS", "main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
