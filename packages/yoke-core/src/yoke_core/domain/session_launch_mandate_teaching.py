"""Worker phase teaching shared with role instructions.

Split out of :mod:`session_launch_mandate` to stay under the authored-file
line budget. The routing module decides WHICH mandate a launch gets; these
are the teachings every one of them carries regardless of route, each
answering a failure a launched worker actually had.

Launches point at the bound skill's phase instructions. These expanded
contracts remain available to teaching verification without being appended
to every launch body.
"""

from __future__ import annotations

from yoke_core.domain.release_wait_ownership import RELEASE_WAIT_RETENTION_TEACHING


PROGRESS_CHECKPOINT_TEACHING = (
    "Keep the item resumable by another worker. Steering may restaff it onto "
    "a different model at any point by terminating this session, which "
    "releases your claim and leaves the lane, its branch, and any "
    "uncommitted work in place for the successor. So before any stop short "
    "of done — a park, a blocker or decision report, a landing or release "
    "wait, or the end of a turn — append a Progress Log checkpoint naming the "
    "live stage, what is committed, what is still uncommitted in the lane, "
    "and the next concrete step: "
    '`yoke items progress-log append PREFIX-N --headline "<checkpoint>" '
    "--stdin`. When the item you claim is already past its first stage, you "
    "are that successor: before acting, read "
    "`yoke items section get PREFIX-N --section 'Progress Log'` and the "
    "lane's `git status` and `git log`, keep the uncommitted work you find, "
    "and resume at the live stage from the last checkpoint rather than "
    "repeating transitions or steps it records as done."
)


LEVEL_HANDOFF_TEACHING = (
    "A transition or merge result may carry handoff with reason level_change: "
    "the item's next stage runs at a different level than your session. That "
    "takes precedence over retaining a release wait. Do exactly this, in "
    "order: (1) append a Progress Log checkpoint naming the live stage, what "
    "is committed, what is uncommitted in the lane, and the next concrete "
    'step (`yoke items progress-log append PREFIX-N --headline "level-change '
    'handoff" --stdin`); (2) release every claim you hold with '
    "`yoke claims work release --all-mine --json` and read the receipt; "
    "(3) run the handoff's next_command exactly as returned, which launches "
    "this item's successor at the new level (a refusal names its recovery: "
    "report it to the orchestrator, keep the checkpoint, and do not continue "
    "at the old level); (4) verify the launch was accepted with "
    "`yoke session-control launch get LAUNCH-ID --json`, then end your "
    "session. Only the item's latest holder, with every claim released, may "
    "launch its own successor; the successor reads your Progress Log and the "
    "preserved lane before acting."
)


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


STEERING_REWORK_TEACHING = (
    "Steering does not gate your landing — it vets your work after it lands "
    "and before the item is admitted to a release. If that vetting finds a "
    "problem, steering tells you what to correct and asks you to move the "
    "item back to implementing — that transition is yours, because "
    "lifecycle.transition requires the calling session to hold the item's "
    "work claim and you are the holder: "
    "`yoke lifecycle transition PREFIX-N --to implementing --reason "
    '"steering rework: <what to correct>"`. '
    "That is a rework leg on the SAME item, not a new one "
    "and not a refusal to argue with: correct it, re-verify, re-land through "
    "the same merge command, and re-enter the release wait. Previous "
    "evidence covered the revision it was taken on and does not carry over "
    "to the corrected one. Escalate instead only when you cannot do the "
    "correction, naming what blocks you."
)


#: Expanded obligations checked against the worker's phase instructions.
STANDING_TEACHINGS = (
    # First: a successor launched onto an in-flight item must resume from
    # the predecessor's checkpoint before it commits or merges anything.
    PROGRESS_CHECKPOINT_TEACHING,
    LEVEL_HANDOFF_TEACHING,
    COMMITTED_GATE_TEACHING,
    # Before the waits: a refusal here means nothing was armed, enqueued, or
    # merged, so the worker needs it before it learns how to wait on any of
    # those.
    CANDIDATE_REVIEW_TEACHING,
    RELEASE_WAIT_RETENTION_TEACHING,
    # After the release wait, because that is where steering's vetting
    # reaches a worker that is already parked and holding its item.
    STEERING_REWORK_TEACHING,
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
    "LEVEL_HANDOFF_TEACHING",
    "PROGRESS_CHECKPOINT_TEACHING",
    "RELEASE_WAIT_RETENTION_TEACHING",
    "STANDING_TEACHINGS",
    "STEERING_REWORK_TEACHING",
]
