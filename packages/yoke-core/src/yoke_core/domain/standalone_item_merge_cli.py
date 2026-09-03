"""Merge a standalone item and optionally close its lifecycle."""

from __future__ import annotations

import json
import sys
from typing import Any, List, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.merge_preflight_github_lock_retry import (
    call_with_machine_lock_retry,
)
from yoke_core.domain import close_out_control_plane_authority as close_out
from yoke_core.domain import standalone_item_merge_evidence as evidence
from yoke_core.domain import standalone_item_merge_landed as landed
from yoke_core.domain import standalone_item_merge_recovery as recovery
from yoke_core.domain import standalone_item_merge_pending as pending
from yoke_core.domain import standalone_item_merge_verify as verify
from yoke_core.domain.session_liveness_pump import SessionLivenessPump
from yoke_core.domain.standalone_item_merge_cli_parser import build_parser
from yoke_core.domain.standalone_item_merge_checkout import (
    ensure_usable_cwd as _ensure_usable_cwd,
    resolve_checkout as _resolve_checkout,
)
from yoke_core.domain.standalone_item_merge_lane import (
    active_lanes,
    lane_branch,
    lane_path,
    lane_resolution_error,
    merge_source_lane,
)
from yoke_core.domain.terminal_lane_cleanup import cleanup_terminal_item_lanes

# Workflows whose terminal transition requires an execution-evidence record.
EVIDENCE_WORKFLOWS = frozenset({"dash"})


def _fail(message: str, *, as_json: bool, **extra: Any) -> int:
    if as_json:
        print(json.dumps({"ok": False, "error": message, **extra}, indent=2))
    else:
        print(f"Error: {message}", file=sys.stderr)
    return 1


def _relay_error(response: Any, fallback: str) -> str:
    return response.error.message if response.error is not None else fallback


def _resolve_item(public_ref: str, project: Optional[str]) -> tuple[Any, str]:
    response = call_with_machine_lock_retry(
        lambda: call_dispatcher(
            function_id="items.detail.get",
            target=TargetRef(kind="item", public_ref=public_ref, project_id=project),
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


def run(argv: List[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    as_json = bool(args.json)

    item, error = _resolve_item(str(args.item), args.project)
    if error:
        return _fail(f"could not resolve item {args.item!r}: {error}", as_json=as_json)

    item_id = int(item["id"])
    public_ref = str(item.get("public_ref") or args.item)
    workflow_id = str((item.get("workflow") or {}).get("id") or "")
    status = str(item.get("status") or "")
    needs_evidence = workflow_id in EVIDENCE_WORKFLOWS and not args.skip_status

    if needs_evidence and not (args.result and args.verification):
        return _fail(
            f"{public_ref} uses the {workflow_id} workflow, whose terminal "
            "transition is evidence-gated: pass --result and --verification "
            "on this command (including when the merge queue already landed "
            "the branch). `yoke lifecycle transition --to done` cannot "
            "restore the work claim close-out needs. Use --skip-status to "
            "merge without closing out.",
            as_json=as_json,
        )

    lane_error = lane_resolution_error(item)
    if active_lanes(item) and lane_error:
        return _fail(
            f"{public_ref}: {lane_error}",
            as_json=as_json,
        )

    branch = lane_branch(item, public_ref)
    claim_error = _session_holds_claim(item_id, str(args.session_id))
    if claim_error:
        # A claim released by a close-out that already completed is not a
        # refusal to report; the item's own record says the work landed.
        closed_out = evidence.closed_out_envelope(
            item,
            public_ref=public_ref,
            branch=branch,
            claim_note=claim_error,
        )
        if closed_out is not None:
            print(json.dumps(closed_out, indent=2, sort_keys=True))
            return 0
        if not recovery.claim_is_missing(claim_error):
            return _fail(f"{public_ref}: {claim_error}", as_json=as_json)

    try:
        repo_root, target = _resolve_checkout(item, str(args.target))
    except RuntimeError as exc:
        return _fail(f"{public_ref}: {exc}", as_json=as_json)
    _ensure_usable_cwd(repo_root, lane_path(item))
    project = str((item.get("project") or {}).get("slug") or "yoke")
    landed_lane = landed.landed_lane(
        item_id=item_id,
        branch=branch,
        target=target,
        repo_root=str(repo_root),
        project=project,
        recorded_head=str((merge_source_lane(item) or {}).get("commit_sha") or ""),
    )
    pruned_lane = not active_lanes(item) and recovery.branch_needs_receipt(
        str(repo_root),
        branch,
    )
    recovered_claim = False
    if claim_error or pruned_lane:
        recovered, recovery_error = recovery.reacquire_landed_claim(
            item_id=item_id,
            session_id=str(args.session_id),
            lane=landed_lane,
        )
        if recovery_error or recovered is None:
            return _fail(
                f"{public_ref}: {recovery_error or 'claim recovery failed'}",
                as_json=as_json,
            )
        item = recovery.with_recorded_head(item, recovered)
        recovered_claim = True

    if landed_lane is not None:
        # Nothing below is safe against a landing that already happened: the
        # commit-bound QA recovery publishes the lane, and the landing route
        # asks the queue to take a pull request it has already merged.
        outcome = landed.converge(
            item_id=item_id,
            project=project,
            repo_root=str(repo_root),
            lane=landed_lane,
            queue_pr_number=str((item.get("merge_queue") or {}).get("pr_number") or ""),
            public_ref=public_ref,
        )
    else:
        outcome, refusal = verify.verify_and_land(
            item,
            args,
            public_ref=public_ref,
            item_id=item_id,
            branch=branch,
            target=target,
            repo_root=repo_root,
            project=project,
        )
        if refusal:
            return _fail(f"{public_ref}: {refusal}", as_json=as_json)
    if not outcome.ok:
        return _fail(
            f"{public_ref}: {outcome.error}",
            as_json=as_json,
            exit_code=outcome.exit_code,
            branch=branch,
            target=target,
        )
    if getattr(outcome, "landing_pending", False) is True:
        pending.print_envelope(item_id, public_ref, branch, target, status, outcome)
        return 0

    close_lane = landed_lane or landed.LandedLane(
        branch=branch,
        target=target,
        commit_sha=outcome.commit_sha,
        merge_sha=outcome.merge_sha,
        touched_files=tuple(outcome.touched_files),
        source="this merge",
    )
    # A claim recovered at admission is already close-out authority. Re-check
    # after landing only when the wait itself could have outlived a claim
    # that was held going in.
    if not recovered_claim and recovery.claim_is_missing(
        _session_holds_claim(item_id, str(args.session_id))
    ):
        item, restore_error = recovery.restore_close_out_claim(
            item=item,
            item_id=item_id,
            session_id=str(args.session_id),
            lane=close_lane,
        )
        if restore_error:
            return _fail(f"{public_ref}: {restore_error}", as_json=as_json)

    envelope: dict[str, Any] = {
        "ok": True,
        "item_id": item_id,
        "public_ref": public_ref,
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
        write_error, write_warning = close_out.record_execution_evidence(
            item_id=item_id,
            outcome=outcome,
            result_summary=str(args.result),
            verification_summary=str(args.verification),
            verification_status=str(args.verification_status),
            no_changes=bool(args.no_changes),
            tree_root=lane_path(item) or str(repo_root),
        )
        if write_error:
            envelope["ok"] = False
            envelope["error"] = f"merge landed, evidence refused: {write_error}"
            print(json.dumps(envelope, indent=2, sort_keys=True))
            return 1
        if write_warning:
            envelope["warnings"].append(write_warning)
        envelope["evidence_recorded"] = True

    from yoke_core.domain.standalone_item_merge import sync_item_to_github

    _announce_close_out("syncing GitHub")
    sync_error = sync_item_to_github(item_id)
    if sync_error:
        envelope["warnings"].append(f"GitHub sync skipped: {sync_error}")

    if not args.skip_status:
        _announce_close_out("terminal transition")
        transition_error = close_out.transition_to_done(
            item_id=item_id,
            source_status=status,
            repo_root=str(repo_root),
            lane=close_lane,
            session_id=str(args.session_id),
        )
        if transition_error:
            # A transition refused on an item another close-out has already
            # finished is a lost race, not a failure: the landing is complete
            # and the refusal's re-acquire hint would re-open a terminal item.
            recorded = evidence.recorded_landing_envelope(
                item_id,
                public_ref=public_ref,
                branch=branch,
            )
            if recorded is not None:
                print(json.dumps(recorded, indent=2, sort_keys=True))
                return 0
            envelope["ok"] = False
            envelope["error"] = (
                f"merge landed and evidence recorded, but the terminal "
                f"transition was refused: {transition_error}"
            )
            print(json.dumps(envelope, indent=2, sort_keys=True))
            return 1
        envelope["status"] = "done"
        _announce_close_out("lane cleanup")
        envelope["warnings"].extend(
            cleanup_terminal_item_lanes(
                {**item, "claim": None},
                target_status="done",
                session_id=str(args.session_id),
                repo_root=repo_root,
                target_branch=target,
            )
        )
        marker_error = pending.clear_after_close_out(item_id, item)
        if marker_error:
            envelope["warnings"].append(f"queue marker not cleared: {marker_error}")

    print(json.dumps(envelope, indent=2, sort_keys=True))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    with SessionLivenessPump().running():
        return run(list(sys.argv[1:] if argv is None else argv))


__all__ = ["EVIDENCE_WORKFLOWS", "main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
