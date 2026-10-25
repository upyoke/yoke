"""Every landing blocker for one item, found in one pass.

`yoke merge item` used to stop on the first gate that refused, so an item
with two unmet gates took two full merge attempts, each with its own
watcher, to learn about both. This module asks every pre-landing question
before anything lands or waits and returns all the failing answers
together, each with its recovery. ``yoke merge item ITEM --check`` prints the
same report and changes nothing.

The questions, in report order: review stage, close-out evidence flags, lane
resolution, checkout, stale unlanded work, work claim (including a pruned
lane with nothing landed), uncommitted lane files, blocking QA proof for the
merging commit, the post-deploy QA answer, then the landing route's own gates
(integration dependencies, candidate review, the merge-queue probe and, for
the standalone engine, the project's verification command). Those route gates
call the functions the landing itself calls, so ``--check`` and the merge
cannot disagree. A lane that already landed skips everything after the clean
tree: nothing is left to prove before a landing that happened. So does a
merge that must recover its claim first: the merge proves the recovered lane
after recovery.

Two conditions are not blockers because the merge resolves them itself: an
item one declared edge before review (the merge enters review), and QA
proof bound only to an older commit of this lane (the merge re-binds it).
They are reported as ``merge_will`` notes. Entering review runs that stage's
gates: the database-claim prose gate is asked here, read-only, and its
refusal is a blocker; the note names the gates only the merge evaluates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from yoke_core.domain import standalone_item_merge_evidence as evidence
from yoke_core.domain import standalone_item_merge_landed as landed
from yoke_core.domain import standalone_item_merge_recovery as recovery
from yoke_core.domain import standalone_item_merge_stale_lane as stale_lane
from yoke_core.domain import standalone_item_merge_verify as verify
from yoke_core.domain.classify_dirty_files import classify_dirty_files
from yoke_core.domain.close_out_evidence_gate import (
    terminal_transition_is_evidence_gated,
)
from yoke_core.domain.merge_queue_landing_timeout import merge_item_resume_command
from yoke_core.domain.merge_queue_route_selection import route_admission
from yoke_core.domain.merge_review_readiness import (
    ReviewReadiness,
    gates_left_to_merge,
    review_entry_refusal,
    review_readiness,
)
from yoke_core.domain.qa_item_stage_plan_gate import missing_item_qa_plan_refusal
from yoke_core.domain.standalone_item_merge_landed import LandedLane
from yoke_core.domain.standalone_item_merge_lane import (
    active_lanes,
    lane_branch,
    lane_path,
    lane_resolution_error,
    merge_source_lane,
)
from yoke_core.domain.standalone_item_merge_release_status import (
    stale_mismatch_is_foreign,
)
from yoke_core.engines.merge_worktree_tests import resolve_verification


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
    #: The claim recovery's answer when it ran here with no landing.
    recovery: Optional[tuple[Optional[LandedLane], str]] = None

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
    blocker, note = verify.proof_check(
        item,
        args,
        public_ref=readiness.public_ref,
        repo_root=readiness.repo_root,
        branch=readiness.branch,
    )
    if blocker:
        readiness.blockers.append(LandingBlocker("QA proof", blocker))
    if note:
        readiness.merge_will.append(note)
    # The unfiltered item: a post-deploy plan is owed whichever transition
    # its attachment names, and the merge-phase view drops some of those.
    plan_refusal = missing_item_qa_plan_refusal(item, public_ref=readiness.public_ref)
    if plan_refusal:
        readiness.blockers.append(LandingBlocker("post-deploy QA", plan_refusal))


def _route_gates(
    readiness: LandingReadiness, item: dict[str, Any], args: Any, head: str
) -> None:
    """The landing route's own gates, asked through the code the landing runs."""
    public_ref = readiness.public_ref
    admission = route_admission(
        item_id=str(item["public_ref"]),
        branch=readiness.branch,
        target=readiness.target,
        repo_root=str(readiness.repo_root),
        project=str((item.get("project") or {}).get("slug") or ""),
        commit_sha=head,
        public_ref=public_ref,
        resume_command=merge_item_resume_command(public_ref, args),
    )
    if admission.refusal:
        readiness.blockers.append(LandingBlocker(admission.gate, admission.refusal))
    elif not admission.declares_queue:
        # The standalone engine resolves this after its rebase; read-only here.
        try:
            resolve_verification(public_ref, materialize=False)
        except RuntimeError as exc:
            readiness.blockers.append(
                LandingBlocker("verification command", f"{public_ref}: {exc}")
            )


def assess(
    item: dict[str, Any],
    args: Any,
    *,
    public_ref: str,
    session_id: str,
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
        entry_refusal = review_entry_refusal(public_ref, readiness.review)
        if entry_refusal:
            add(LandingBlocker("review entry", f"{public_ref}: {entry_refusal}"))
        left = gates_left_to_merge(readiness.review)
        readiness.merge_will.append(
            f"move {public_ref} from {readiness.review.source_stage!r} to "
            f"{readiness.review.review_stage!r} with --verification as the "
            "reason"
            + (
                f", evaluating that stage's gates {', '.join(left)} only then "
                "(this check has not run them)"
                if left
                else ""
            )
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

    missing_claim = recovery.claim_is_missing(readiness.claim_error)
    if readiness.claim_error and not missing_claim:
        add(LandingBlocker("work claim", f"{public_ref}: {readiness.claim_error}"))
    pruned_lane = not active_lanes(item) and recovery.branch_needs_receipt(
        repo_root, readiness.branch
    )
    if (missing_claim or pruned_lane) and (missing_claim or not readiness.claim_error):
        if readiness.landed is None:
            # With no landing this reads only: it names why recovery refuses.
            readiness.recovery = recovery.reacquire_landed_claim(
                item_id=item_id, session_id=session_id, lane=None, item=item
            )
            refusal = readiness.recovery[1] or (
                "" if readiness.recovery[0] else "claim recovery failed"
            )
            if refusal:
                add(LandingBlocker("work claim", f"{public_ref}: {refusal}"))
        else:
            readiness.merge_will.append(
                "re-acquire the work claim for the landed lane's close-out"
            )

    dirty = _dirty_lane_files(item)
    if dirty:
        add(LandingBlocker(
            "clean tree",
            f"lane {lane_path(item)} has uncommitted files the landing would "
            f"leave behind: {', '.join(dirty)}. Commit them on the lane "
            "branch, or remove them, then re-run.",
        ))

    # A lane that already landed has nothing left to prove; a claim recovery
    # changes the item the proof is read from, so the merge proves it after.
    if readiness.landed is None and not (missing_claim or pruned_lane):
        _qa_gates(readiness, item, args)
        _route_gates(readiness, item, args, recorded_head)
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
