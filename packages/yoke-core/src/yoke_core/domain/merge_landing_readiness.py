"""Every landing blocker for one item, found in one pass.

`yoke merge item` used to stop on the first gate that refused, so an item
with two unmet gates took two full merge attempts, each with its own
watcher, to learn about both. This module asks every pre-landing question
before anything lands or waits and returns all the failing answers
together, each with its recovery. ``yoke merge item ITEM --check`` prints the
same report and changes nothing.

The questions, in report order: review stage, close-out evidence flags, lane
resolution, checkout, stale unlanded work, a missing lane with no landing,
work claim, uncommitted lane files, blocking QA proof for the merging commit, and the post-deploy QA
answer. A lane that already landed skips the last two: nothing is left to
prove before a landing that happened.

Two conditions are not blockers because the merge resolves them itself: an
item one declared edge before review (the merge enters review), and QA
proof bound only to an older commit of this lane (the merge re-binds it).
They are reported as ``merge_will`` notes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from yoke_core.domain import standalone_item_merge_commit_bound as commit_bound
from yoke_core.domain import standalone_item_merge_evidence as evidence
from yoke_core.domain import standalone_item_merge_landed as landed
from yoke_core.domain import standalone_item_merge_recovery as recovery
from yoke_core.domain import standalone_item_merge_stale_lane as stale_lane
from yoke_core.domain.classify_dirty_files import classify_dirty_files
from yoke_core.domain.close_out_evidence_gate import (
    terminal_transition_is_evidence_gated,
)
from yoke_core.domain.merge_review_readiness import ReviewReadiness, review_readiness
from yoke_core.domain.qa_item_stage_plan_gate import missing_item_qa_plan_refusal
from yoke_core.domain.qa_terminal_settlement import requirement_issue_errors
from yoke_core.domain.standalone_item_merge_landed import LandedLane
from yoke_core.domain.standalone_item_merge_lane import (
    active_lanes,
    lane_branch,
    lane_path,
    lane_resolution_error,
    merge_source_lane,
)
from yoke_core.domain.standalone_item_merge_qa import evaluate, item_for_merge_phase
from yoke_core.domain.standalone_item_merge_release_status import (
    stale_mismatch_is_foreign,
)


@dataclass(frozen=True)
class LandingBlocker:
    """One failing gate and the text that names its recovery."""

    gate: str
    reason: str


@dataclass
class LandingReadiness:
    """The whole pre-landing answer for one item."""

    public_ref: str
    branch: str
    review: ReviewReadiness = field(default_factory=ReviewReadiness)
    blockers: list[LandingBlocker] = field(default_factory=list)
    merge_will: list[str] = field(default_factory=list)
    claim_error: str = ""
    closed_out: bool = False
    repo_root: Optional[Path] = None
    target: str = ""
    landed: Optional[LandedLane] = None

    @property
    def ready(self) -> bool:
        return not self.blockers

    def refusal(self) -> str:
        """Every blocker in one message, each with its recovery."""
        count = len(self.blockers)
        lines = [
            f"merge refused before the branch landed: {count} landing "
            f"blocker{'s' if count != 1 else ''}. Fix every one, check again "
            f"with `yoke merge item {self.public_ref} --check`, then re-run "
            "this merge."
        ]
        for blocker in self.blockers:
            lines.append(f"[{blocker.gate}] {blocker.reason}")
        return "\n".join(lines)

    def report(self) -> dict[str, Any]:
        return {
            "ok": self.ready,
            "public_ref": self.public_ref,
            "ready": self.ready,
            "blockers": [
                {"gate": blocker.gate, "reason": blocker.reason}
                for blocker in self.blockers
            ],
            "merge_will": list(self.merge_will),
        }


def _dirty_lane_files(item: dict[str, Any]) -> list[str]:
    path = lane_path(item)
    if not path or not Path(path).is_dir():
        return []
    _yoke_files, user_files = classify_dirty_files(repo_path=path)
    return sorted(user_files)


def _qa_gates(readiness: LandingReadiness, item: dict[str, Any], args: Any) -> None:
    qa_item = item_for_merge_phase(
        item, leaves_status_unchanged=bool(args.skip_status)
    )
    _sha, issues, error = evaluate(
        qa_item,
        public_ref=readiness.public_ref,
        repo_root=readiness.repo_root,
        branch=readiness.branch,
    )
    if error:
        readiness.blockers.append(LandingBlocker("QA proof", error))
    elif commit_bound.is_commit_bound_refusal(issues):
        readiness.merge_will.append(
            "re-bind passing QA proof recorded for an older commit of this "
            "lane to the merging commit"
        )
    elif issues:
        errors = requirement_issue_errors(
            issues, public_ref=readiness.public_ref, target_status="done"
        )
        readiness.blockers.append(LandingBlocker("QA proof", "\n".join(errors)))
    plan_refusal = missing_item_qa_plan_refusal(item, public_ref=readiness.public_ref)
    if plan_refusal:
        readiness.blockers.append(LandingBlocker("post-deploy QA", plan_refusal))


def assess(
    item: dict[str, Any],
    args: Any,
    *,
    public_ref: str,
    claim_error: Callable[[str], str],
    resolve_checkout: Callable[[dict[str, Any], str], tuple[Path, str]],
) -> LandingReadiness:
    """Ask every pre-landing question. Reads only; never lands or writes.

    ``claim_error`` explains why the calling session does not hold the item
    claim (empty when it does); ``resolve_checkout`` returns the checkout and
    base branch the lane lands in. The merge command supplies both.
    """
    item_id = str(item["public_ref"])
    status = str(item.get("status") or "")
    readiness = LandingReadiness(
        public_ref=public_ref, branch=lane_branch(item, public_ref)
    )
    readiness.claim_error = claim_error(item_id)
    if readiness.claim_error and evidence.closed_out_envelope(
        item,
        public_ref=public_ref,
        branch=readiness.branch,
        claim_note=readiness.claim_error,
    ):
        # The record says the work already landed and closed out; the merge
        # reports that instead of gating it.
        readiness.closed_out = True
        return readiness
    add = readiness.blockers.append

    readiness.review = review_readiness(item, public_ref=public_ref)
    if readiness.review.refusal:
        add(LandingBlocker("review stage", readiness.review.refusal))
    elif readiness.review.enters_review:
        readiness.merge_will.append(
            f"move {public_ref} from {readiness.review.source_stage!r} to "
            f"{readiness.review.review_stage!r} (that stage's gates run) "
            "with --verification as the reason"
        )

    workflow_id = str((item.get("workflow") or {}).get("id") or "")
    if (
        terminal_transition_is_evidence_gated(workflow_id)
        and not args.skip_status
        and not (args.result and args.verification)
    ):
        add(LandingBlocker(
            "close-out evidence",
            f"{public_ref} uses the {workflow_id} workflow, whose terminal "
            "transition is evidence-gated: pass --result and --verification "
            "on this command (including when the merge queue already landed "
            "the branch). `yoke lifecycle transition --to done` cannot "
            "restore the work claim close-out needs. Use --skip-status to "
            "merge without closing out.",
        ))

    lane_error = lane_resolution_error(item)
    if active_lanes(item) and lane_error:
        add(LandingBlocker("lane", f"{public_ref}: {lane_error}"))

    try:
        readiness.repo_root, readiness.target = resolve_checkout(
            item, str(args.target)
        )
    except RuntimeError as exc:
        add(LandingBlocker("checkout", f"{public_ref}: {exc}"))
        return readiness
    repo_root = str(readiness.repo_root)
    recorded_head = str((merge_source_lane(item) or {}).get("commit_sha") or "")
    queue = item.get("merge_queue") or {}
    stale = stale_lane.stale_unlanded_work(
        item_id=item_id,
        branch=readiness.branch,
        target=readiness.target,
        repo_root=repo_root,
        recorded_head=recorded_head,
        stale_mismatch_is_foreign=stale_mismatch_is_foreign(item, status),
    )
    # A recorded queue landing that does not cover this candidate is the
    # false-success recovery: take the candidate path even from release.
    if stale and not (queue.get("pr_number") and queue.get("landed_at")):
        add(LandingBlocker("stale lane", f"{public_ref}: {stale}"))
    readiness.landed = landed.landed_lane(
        item_id=item_id,
        branch=readiness.branch,
        target=readiness.target,
        repo_root=repo_root,
        project=str((item.get("project") or {}).get("slug") or ""),
        recorded_head=recorded_head,
    )

    pruned_lane = not active_lanes(item) and recovery.branch_needs_receipt(
        repo_root, readiness.branch
    )
    if pruned_lane and readiness.landed is None and not readiness.claim_error:
        add(LandingBlocker("lane", recovery.missing_lane_refusal(item_id, item)))
    if readiness.claim_error:
        if recovery.claim_is_missing(readiness.claim_error) and readiness.landed:
            readiness.merge_will.append(
                "re-acquire the work claim for the landed lane's close-out"
            )
        else:
            add(LandingBlocker("work claim", f"{public_ref}: {readiness.claim_error}"))

    dirty = _dirty_lane_files(item)
    if dirty:
        add(LandingBlocker(
            "clean tree",
            f"lane {lane_path(item)} has uncommitted files the landing would "
            f"leave behind: {', '.join(dirty)}. Commit them on the lane "
            "branch, or remove them, then re-run.",
        ))

    if readiness.landed is None:
        _qa_gates(readiness, item, args)
    return readiness


def print_check(readiness: LandingReadiness, *, as_json: bool) -> int:
    """Print the ``--check`` report. Exit 0 when the item may land, else 1."""
    if as_json:
        print(json.dumps(readiness.report(), indent=2, sort_keys=True))
        return 0 if readiness.ready else 1
    if readiness.closed_out:
        print(f"{readiness.public_ref}: already landed and closed out.")
        return 0
    if readiness.ready:
        print(f"{readiness.public_ref}: ready to land.")
    else:
        print(readiness.refusal())
    for note in readiness.merge_will:
        print(f"The merge will {note}.")
    return 0 if readiness.ready else 1


__all__ = ["LandingBlocker", "LandingReadiness", "assess", "print_check"]
