"""Merge a standalone item and optionally close its lifecycle."""

from __future__ import annotations

import json
import sys
from functools import partial
from typing import Any, List, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.merge_preflight_github_lock_retry import (
    call_with_machine_lock_retry,
)
from yoke_core.domain import close_out_control_plane_authority as close_out
from yoke_core.domain import standalone_item_merge as merge_domain
from yoke_core.domain import standalone_item_merge_close_out_report as report
from yoke_core.domain import standalone_item_merge_converge as converge
from yoke_core.domain import standalone_item_merge_evidence as evidence
from yoke_core.domain import standalone_item_merge_landed as landed
from yoke_core.domain import standalone_item_merge_stale_lane as stale_lane
from yoke_core.domain import standalone_item_merge_recovery as recovery
from yoke_core.domain import standalone_item_merge_release_continuation as release_flow
from yoke_core.domain.merge_review_readiness import review_readiness_refusal
from yoke_core.domain.standalone_item_merge_close_out_transition import (
    run_terminal_transition,
)
from yoke_core.domain.standalone_item_merge_release_status import (
    stale_mismatch_is_foreign,
)
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
from yoke_core.domain.terminal_lane_cleanup import record_terminal_lane_close_out

# Workflows whose terminal transition requires an execution-evidence record.
EVIDENCE_WORKFLOWS = frozenset({"dash"})


def _fail(message: str, *, as_json: bool, public_ref: str = "", **extra: Any) -> int:
    if as_json:
        print(json.dumps({"ok": False, "error": message, **extra}, indent=2))
    else:
        print(f"Error: {message}", file=sys.stderr)
    report.print_outcome(kind=report.NOT_CLOSED, public_ref=public_ref, blocker=message)
    return 1


def _session_holds_claim(item_id: int, session_id: str) -> str:
    """Empty when this session owns the item claim, else why it does not."""
    return recovery.claim_error(item_id, session_id)


def _resolve_item(public_ref: str, project: Optional[str]) -> tuple[Any, str]:
    response = call_with_machine_lock_retry(
        lambda: call_dispatcher(
            function_id="items.detail.get",
            target=TargetRef(kind="item", public_ref=public_ref, project_id=project),
            payload={},
        )
    )
    if not response.success:
        error = response.error
        return None, error.message if error is not None else "item resolution failed"
    return (response.result or {}).get("item") or {}, ""


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
    fail = partial(_fail, as_json=as_json, public_ref=public_ref)
    announce = report.bind(session_id=str(args.session_id), dispatch=call_dispatcher)
    workflow_id = str((item.get("workflow") or {}).get("id") or "")
    status = str(item.get("status") or "")
    evidence_workflow = workflow_id in EVIDENCE_WORKFLOWS
    # The close-out that will transition needs the summaries up front. The
    # write itself is owed by the merge, not by the transition: evidence
    # describes the landing, so a caller that supplied it gets it recorded
    # even when the status change is postponed to a later command.
    close_out_gated = evidence_workflow and not args.skip_status
    record_evidence = evidence_workflow and bool(args.result and args.verification)

    unready = review_readiness_refusal(item, public_ref=public_ref)
    if unready:
        return fail(unready)

    if close_out_gated and not (args.result and args.verification):
        return fail(
            f"{public_ref} uses the {workflow_id} workflow, whose terminal "
            "transition is evidence-gated: pass --result and --verification "
            "on this command (including when the merge queue already landed "
            "the branch). `yoke lifecycle transition --to done` cannot "
            "restore the work claim close-out needs. Use --skip-status to "
            "merge without closing out.",
        )

    lane_error = lane_resolution_error(item)
    if active_lanes(item) and lane_error:
        return fail(f"{public_ref}: {lane_error}")

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
            record_terminal_lane_close_out(
                item,
                closed_out,
                target_status=status,
                session_id=str(args.session_id),
            )
            print(json.dumps(closed_out, indent=2, sort_keys=True))
            announce(closed_out, kind=report.ALREADY_CLOSED, evidence_from_record=True)
            return 0
        if not recovery.claim_is_missing(claim_error):
            return fail(f"{public_ref}: {claim_error}")

    try:
        repo_root, target = _resolve_checkout(item, str(args.target))
    except RuntimeError as exc:
        return fail(f"{public_ref}: {exc}")
    _ensure_usable_cwd(repo_root, lane_path(item))
    project = str((item.get("project") or {}).get("slug") or "yoke")
    recorded_head = str((merge_source_lane(item) or {}).get("commit_sha") or "")
    stale = stale_lane.stale_unlanded_work(
        item_id=item_id,
        branch=branch,
        target=target,
        repo_root=str(repo_root),
        recorded_head=recorded_head,
        stale_mismatch_is_foreign=stale_mismatch_is_foreign(item, status),
    )
    queue = item.get("merge_queue") or {}
    # A recorded queue landing that does not cover this candidate is the
    # false-success recovery: take the candidate path even from release.
    if stale and not (queue.get("pr_number") and queue.get("landed_at")):
        return fail(f"{public_ref}: {stale}")
    landed_lane = landed.landed_lane(
        item_id=item_id,
        branch=branch,
        target=target,
        repo_root=str(repo_root),
        project=project,
        recorded_head=recorded_head,
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
            return fail(f"{public_ref}: {recovery_error or 'claim recovery failed'}")
        item = recovery.with_recorded_head(item, recovered)
        recovered_claim = True

    if landed_lane is not None:
        # Nothing below is safe against a landing that already happened: the
        # commit-bound QA recovery publishes the lane, and the landing route
        # asks the queue to take a pull request it has already merged.
        outcome = converge.converge(
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
            return fail(f"{public_ref}: {refusal}")
    if not outcome.ok:
        return fail(
            f"{public_ref}: {outcome.error}",
            exit_code=outcome.exit_code,
            branch=branch,
            target=target,
        )
    if getattr(outcome, "landing_pending", False) is True:
        landing = pending.print_envelope(
            item_id, public_ref, branch, target, status, outcome
        )
        announce(landing, kind=report.LANDING_PENDING)
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
            return fail(f"{public_ref}: {restore_error}")

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

    if record_evidence:
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
            announce(envelope, kind=report.NOT_CLOSED)
            return 1
        if write_warning:
            envelope["warnings"].append(write_warning)
        envelope["evidence_recorded"] = True

    _announce_close_out("prepared release")
    release_fragment, release_warning = release_flow.continue_prepared_release(
        item_id=item_id, session_id=str(args.session_id), public_ref=public_ref,
    )
    if release_fragment is not None:
        envelope["prepared_release"] = release_fragment
    if release_warning:
        envelope["warnings"].append(release_warning)

    _announce_close_out("syncing GitHub")
    if sync_error := merge_domain.sync_item_to_github(item_id):
        envelope["warnings"].append(f"GitHub sync skipped: {sync_error}")

    exit_code = run_terminal_transition(
        item=item,
        item_id=item_id,
        public_ref=public_ref,
        branch=branch,
        target=target,
        status=status,
        close_lane=close_lane,
        session_id=str(args.session_id),
        repo_root=repo_root,
        envelope=envelope,
        announce=_announce_close_out,
        close_out=close_out,
        evidence=evidence,
        pending=pending,
        record_terminal_lane_close_out=record_terminal_lane_close_out,
        postpone_terminal=bool(args.skip_status),
    )
    if exit_code is not None:
        print(json.dumps(envelope, indent=2, sort_keys=True))
        announce(
            envelope,
            kind=report.ALREADY_CLOSED if exit_code == 0 else report.NOT_CLOSED,
            evidence_from_record=exit_code == 0,
        )
        return exit_code

    print(json.dumps(envelope, indent=2, sort_keys=True))
    kind, blocker = report.final_outcome(
        envelope, source_status=status, skip_status=bool(args.skip_status)
    )
    announce(envelope, kind=kind, blocker=blocker)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    with SessionLivenessPump().running():
        return run(list(sys.argv[1:] if argv is None else argv))


__all__ = ["EVIDENCE_WORKFLOWS", "main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
