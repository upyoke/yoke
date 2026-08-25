"""Merge a standalone item and optionally close its lifecycle."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, List, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.merge_preflight_github_lock_retry import (
    call_with_machine_lock_retry,
)
from yoke_core.domain import standalone_item_merge_evidence as evidence
from yoke_core.domain import standalone_item_merge_landed as landed
from yoke_core.domain import standalone_item_merge_recovery as recovery
from yoke_core.domain import standalone_item_merge_terminal as terminal
from yoke_core.domain import standalone_item_merge_verify as verify
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
    merge_source_lane,
)
from yoke_core.domain.terminal_lane_cleanup import cleanup_terminal_item_lanes
from yoke_contracts.dash_evidence_status import status_argument_kwargs

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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yoke merge item")
    parser.add_argument("item")
    parser.add_argument("--project")
    parser.add_argument("--target", default="", help="Override the base branch.")
    parser.add_argument("--session-id", default=os.environ.get("YOKE_SESSION_ID", ""))
    parser.add_argument("--result", default="", help="What changed or was learned.")
    parser.add_argument("--verification", default="", help="Verification evidence.")
    parser.add_argument("--verification-status", **status_argument_kwargs())
    boolean_options = (
        ("--no-changes", "Record a verified no-change result."),
        ("--skip-status", "Merge without changing lifecycle status."),
        ("--pr", "Merge through a pull request."),
    )
    for flag, help_text in boolean_options:
        parser.add_argument(flag, action="store_true", help=help_text)
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
            f"{item_ref}: {lane_error}",
            as_json=as_json,
        )

    branch = lane_branch(item, item_ref)
    claim_error = _session_holds_claim(item_id, str(args.session_id))
    if claim_error:
        # A claim released by a close-out that already completed is not a
        # refusal to report; the item's own record says the work landed.
        closed_out = evidence.closed_out_envelope(
            item,
            item_ref=item_ref,
            branch=branch,
            claim_note=claim_error,
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
    project = str((item.get("project") or {}).get("slug") or "yoke")
    landed_lane = landed.landed_lane(
        item_id=item_id,
        branch=branch,
        target=target,
        repo_root=str(repo_root),
        project=project,
        recorded_head=str(
            (merge_source_lane(item) or {}).get("commit_sha") or ""
        ),
    )
    pruned_lane = not active_lanes(item) and recovery.branch_needs_receipt(
        str(repo_root),
        branch,
    )
    if claim_error or pruned_lane:
        recovered, recovery_error = recovery.reacquire_landed_claim(
            item_id=item_id,
            session_id=str(args.session_id),
            lane=landed_lane,
        )
        if recovery_error or recovered is None:
            return _fail(
                f"{item_ref}: {recovery_error or 'claim recovery failed'}",
                as_json=as_json,
            )
        item = recovery.with_recorded_head(item, recovered)

    if landed_lane is not None:
        # Nothing below is safe against a landing that already happened: the
        # commit-bound QA recovery publishes the lane, and the landing route
        # asks the queue to take a pull request it has already merged.
        outcome = landed.converge(
            item_id=item_id,
            project=project,
            repo_root=str(repo_root),
            lane=landed_lane,
        )
    else:
        outcome, refusal = verify.verify_and_land(
            item,
            args,
            item_ref=item_ref,
            item_id=item_id,
            branch=branch,
            target=target,
            repo_root=repo_root,
            project=project,
        )
        if refusal:
            return _fail(f"{item_ref}: {refusal}", as_json=as_json)
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
            item_id,
            outcome.merge_sha,
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
        transition_error = terminal.transition_to_done(
            item_id=item_id,
            source_status=status,
            repo_root=str(repo_root),
            lane=landed_lane or landed.LandedLane(
                branch=branch,
                target=target,
                commit_sha=outcome.commit_sha,
                merge_sha=outcome.merge_sha,
                touched_files=tuple(outcome.touched_files),
                source="this merge",
            ),
            session_id=str(args.session_id),
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
        envelope["warnings"].extend(
            cleanup_terminal_item_lanes(
                {**item, "claim": None},
                target_status="done",
                session_id=str(args.session_id),
                repo_root=repo_root,
                target_branch=target,
            )
        )

    print(json.dumps(envelope, indent=2, sort_keys=True))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    with SessionLivenessPump().running():
        return run(list(sys.argv[1:] if argv is None else argv))


__all__ = ["EVIDENCE_WORKFLOWS", "main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
