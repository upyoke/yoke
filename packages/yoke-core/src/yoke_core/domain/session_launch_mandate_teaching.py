"""The fixed paragraphs every composed worker mandate carries.

Split out of :mod:`session_launch_mandate` to stay under the authored-file
line budget. The routing module decides WHICH mandate a launch gets; these
are the teachings every one of them carries regardless of route, each
answering a failure a launched worker actually had.

They live together because they are read together: a worker meets them as
one block at the end of its mandate, and a change to one that contradicts
another is the defect this module exists to make visible.
"""

from __future__ import annotations

from yoke_core.domain.release_wait_ownership import RELEASE_WAIT_RETENTION_TEACHING


COMMITTED_GATE_TEACHING = (
    "Commit; the verification gate rebases onto the base branch, pushes "
    "once, and runs CI. Workers do not push the lane by hand."
)


HEADLESS_CI_VERIFICATION_WAIT_TEACHING = (
    "Before any of that, `yoke merge item` may itself dispatch or attach to "
    "a CI run for its own post-rebase verification and poll it to a "
    "conclusion. That poll registers a durable wait, the same mechanism a "
    "merge-queue landing uses, so a turn that stops there is normally woken "
    "with the verdict too. Registration can fail — the command warns by "
    "name rather than promising a wake it cannot keep — so either way, "
    "re-run the same `yoke merge item` command: it rejoins the run by exact "
    "commit and adopts its conclusion instead of dispatching another suite. "
    "Never replace either path with local GitHub polling."
)


HEADLESS_LANDING_WAIT_TEACHING = (
    "You are a headless command that cannot be prompted again, so a "
    "merge-queue landing is not yours to wait out: it outlasts your turn, and "
    "a wait that dies with the turn leaves the branch landed and the item "
    "open. Your merge arms the landing and returns landing_pending=true with "
    "the pull request named, whether or not you passed --wait. That is the "
    "handoff, not a failure. Report the pull request, stop deliberately, and "
    "say you are waiting on landing. The control-plane landing notice wakes "
    "you: re-run the same `yoke merge item` command then and it completes "
    "close-out. A stopped landing arrives the same way and names its recovery "
    "(usually rebase, re-run the verification gate, re-run the command); a "
    "stale server landing record names its last refresh and repair step. "
    "Never replace either with local GitHub polling, and never report a "
    "landing you did not read."
)


HEADLESS_TOOL_CONTINUATION_TEACHING = (
    "A tool call that outlives its yield is still running. When your harness "
    "moves a long command to a background task or hands back a continuation "
    "handle, that is the harness handing the call back, not an interruption: "
    "the child and whatever it is waiting on are still alive. Continue that "
    "same call through your harness's continuation surface until it exits "
    "and you have read its outcome — reading the background task's output "
    "continues the call, and only ending the turn kills the watcher and the "
    "child it was holding, which lands as a killed capture with no recorded "
    "verdict. Never start a second invocation beside a live one; re-run only "
    "once the first process is verifiably gone. Stop before a command "
    "finishes only where the command itself handed the wait off — a merge "
    "that returned landing_pending has its landing notice — or, as the "
    "explicitly taught exception, when a *local* test check on a project "
    "with declared CI has already exceeded about one minute: interrupt "
    "that test process cleanly, keep the capture as incomplete, commit, "
    "and continue the selection on that project's CI. Do not interrupt a "
    "CI-routed watcher, a machine-specific diagnostic, or a local run on "
    "a project without CI, and do not background the slow local selection "
    "to keep waiting."
)


_DELIBERATE_CLOSE = (
    "Ending a turn sends no Fleet message. When those legs are complete, "
    "message the orchestrator "
    '(printf %s "DONE {ref} <one-line summary>" | yoke say --stdin '
    "--steering) and END your session — do not pick up further work, do not "
    "chain into other items. Send that report before releasing any claim you "
    "still hold; after a close-out that already released it, --steering "
    "resolves from the item you last held in this session. The PREFIX-N in "
    "the DONE heading is the report identity and must name work this session "
    "holds or released; a repeat of the same DONE is deduplicated rather "
    "than delivered twice. A completion you are later RESUMED to do is its "
    "own leg and reaches the seat on its own, whether or not that resume "
    "hands you a fresh claim — never release an unfinished lane to force "
    "one through. A send answering `Collapsed into an earlier message` did "
    "NOT deliver your body; read it rather than assume you reported. "
    "Complete means the item reached its own terminal status: a close-out "
    "that stopped at a pinned release wait has NOT completed those legs, "
    "and neither the report nor the END is owed yet."
)


CANDIDATE_REVIEW_TEACHING = (
    "An item whose posture selects merge_candidate_review may not land "
    "until a person has cleared the exact commit. `yoke merge item` refuses "
    "an uncleared candidate by name, before it arms, enqueues, or merges "
    "anything, and names the open decision request an authorized reviewer "
    "answers. You cannot answer it yourself: the session holding the item's "
    "work claim is refused by name, whatever actor it carries, and so is "
    "clearing the posture key. That refusal is a blocker, not a retry: "
    "report it with the request id and stop. Any commit you make after a "
    "clearance needs its own review, so commit everything first, then "
    "merge."
)


#: Appended to every composed mandate, in the order a worker meets them.
STANDING_TEACHINGS = (
    COMMITTED_GATE_TEACHING,
    # Before the waits: a refusal here means nothing was armed, enqueued, or
    # merged, so the worker needs it before it learns how to wait on any of
    # those.
    CANDIDATE_REVIEW_TEACHING,
    RELEASE_WAIT_RETENTION_TEACHING,
    HEADLESS_CI_VERIFICATION_WAIT_TEACHING,
    HEADLESS_LANDING_WAIT_TEACHING,
    HEADLESS_TOOL_CONTINUATION_TEACHING,
)


__all__ = [
    "CANDIDATE_REVIEW_TEACHING",
    "COMMITTED_GATE_TEACHING",
    "HEADLESS_CI_VERIFICATION_WAIT_TEACHING",
    "HEADLESS_LANDING_WAIT_TEACHING",
    "HEADLESS_TOOL_CONTINUATION_TEACHING",
    "RELEASE_WAIT_RETENTION_TEACHING",
    "STANDING_TEACHINGS",
]
