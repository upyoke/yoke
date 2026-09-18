# Dash phase 6 — confirm the verified tree and land it

## Confirm the tree

Immediately before merge, resolve the exact touched set again and replace the
survey with every actual file:

```text
yoke direct-workflow dash survey ITEM --path <actual-file> [--path <actual-file> ...] --json
yoke direct-workflow dash survey ITEM --no-changes --json  # genuine no-change only
```

Read any reported contacts as advisories here too; a recorded overlap does not
itself prevent merge. Proceed when the edits are independent. For
order-dependent work, wait for the holding work to land (merge receipt,
merged_at, or git ancestry — not status) and re-run the survey; for an
unresolved contact, release the work claim and present the path, holder, and
evidence to the operator.

Then require a clean worktree whose HEAD is the tree named by every passing
SHA-bound verdict. Any intervening edit, commit, amend, or rebase invalidates
the old verdict: commit the final tree and rerun the affected case. Do not
merge by hand, force-push, bypass CI, or merge around a registered claim.

## A candidate a person must clear

When the item's posture selects `merge_candidate_review`, `yoke merge item`
refuses before it arms, enqueues, or merges anything, because the exact
commit the landing would carry has to be cleared first. The refusal names
the open decision request; it sits in a reviewer's Inbox, and they answer it
with `yoke decision-requests resolve REQUEST_ID approve`.

You cannot answer it yourself. The session holding the item's work claim is
refused by name — the actor you carry is the operator's own, so the session
is what separates the work from its review. Clearing the posture key is
refused for the same reason.

That refusal is a blocker, not a retry — report it with the request id and
stop rather than re-running the merge in a loop. The clearance is bound to
the commit, so commit everything first and merge second: any commit made
after a clearance is a different candidate and asks again. `yoke merge-review
candidate evaluate ITEM --commit SHA` reports where a candidate stands
without attempting a landing.

## The merge command may verify on CI itself

Before any landing shape below, `yoke merge item` itself may dispatch or
attach to a CI run for post-rebase verification and poll it to a
conclusion — this happens inside the same command, not as a separate step.
That poll registers a durable wait, the same mechanism the landing notice
below uses, so a turn that stops mid-poll is normally woken with the
verdict. Registration can fail — the command warns by name rather than
promising a wake it cannot keep — so either way, re-run the same
`yoke merge item` command: it rejoins the run by exact commit and adopts
its conclusion instead of dispatching another suite. Never replace either
path with local GitHub polling.

## Two landing shapes, and the merge decides which

**A relay-launched session arms the landing and stops.** `yoke merge item`
returns `landing_pending=true` naming the pull request, whatever you passed,
because a headless command cannot outlive a queue landing: the wait would die
with the turn and leave the branch landed with the item open. Report the pull
request, say you are waiting on landing, and end the turn deliberately — the
Stop gate treats a recorded pending landing as a legitimate stop. The
control-plane landing notice wakes you, and re-running the same
`yoke merge item ITEM --result ... --verification ...` command then completes
close-out, exactly as it does for any landed-but-not-closed-out item. A stopped
landing arrives the same way and names its recovery.

**Every other session waits.** The watcher invocation's safe wait shape is
resolved from the calling session's manifest wake capability, never from who
opened the session, its executor name, or whether Yoke can reach it over a
relay. A native idle-wake primitive preserves the background subscription; a
harness with no or unverified idle wake keeps the wait in the current turn.
The primitive resumes the turn in place, so a desktop conversation waits
exactly as its CLI sibling does.

Either way the first call opens / rebases / arms the pull request and returns
`landing_pending=true`, which means GitHub itself reported that it holds the
landing — armed or already queued, still mergeable, and with none of its own
required checks already red — read back rather than inferred from the arming
request succeeding. GitHub creates the queue entry only once those checks pass,
so armed-and-not-yet-queued is the ordinary state here; an arming that never
took, a pull request that is no longer mergeable, and one whose required checks
have already concluded red each refuse instead and name which of those four it
saw. A red required check refuses before anything is armed, and names the check
and its run.

## Wake-routed wait

Pass `--wait` through the merge watcher wrapper. A relay-launched session takes
the arm-and-stop handoff above instead, so nothing below applies to it. On each
documented cadence the waiting client calls `merge_queue.landing.observe`. The
server rate-limits concurrent callers to one project-wide GitHub sweep per
cadence, refreshes every pending landing, and returns this lane's durable
record. It preserves the same four-fact landing readback (armed, queued,
eligible, required checks) as structured pull-request state, queue holding,
named queue-entry state, merge-when-ready state, head SHA, failed checks, and
refresh/change times. The waiting machine issues no `gh`, GitHub, or
`git fetch` read loop. Landing-complete/stopped record changes still use the
existing explicit session wake for a detached holder. The wrapper streams
changed records and writes the exit sentinel that ends the follow; it never
needs a hand-authored `gh` poll loop:

```text
yoke watch merge --print-streaming-pair merge-item -- ITEM --wait \
  --result "<what changed>" --verification "<checks and evidence>"
```

That call only prints: it merges nothing, arms nothing, and records nothing.
Read the reported `wait_mode` and reason, then run the printed command exactly
once — that run is the merge.

A `[phase:authority] tunnel_busy ... elapsed=.../limit=...` line means a
sibling merge still owns the machine's connected-environment tunnel lifecycle
step. Leave that holder running and keep this invocation open: the merge waits
through one more bounded replacement window and continues when the tunnel is
free.

- `background-wake` means the caller's harness can resume an ended turn. The
  printed pair is the bound background command and its subscription; run that
  pair exactly once on the long-command surface your harness rules name. A
  completion wake is expected only because the mode line recorded that
  primitive.
- `in-turn` means the printed command is a single foreground invocation that
  holds the wait and will not return until landing finishes. Run it, and keep
  the call open. No later completion notice is expected. On Claude, set the
  Bash tool's `timeout` to `600000` on every `in-turn` watcher invocation, so
  the harness does not move the call to a background task at its 120-second
  default. Headless Claude watcher Bash that omits it is denied by
  `lint-headless-watcher-timeout` — not a blanket Bash rule. If it moves the
  call anyway, the command is still running: continue that same call through
  the background task's output until it exits. Reading that output continues
  the call — only ending the turn kills the watcher and the child it was
  holding. Existing Stop evidence cannot hold after that PostToolUse
  completion.

For a separate point-in-time check, run
`yoke github merge-queue readiness ITEM --json`. It reads the target branch's
named queue entry with arming, so null arming plus
`queue-entry=AWAITING_CHECKS` means consumed and in flight, not cleared.

## Hold a live candidate before correcting it

While the pull request is armed or queued, every lane publish — the
verification gate, the remote pytest selection, and the landing's own retry —
refuses instead of pushing a commit the queue would strand on no branch.
Disabling auto-merge does not remove an entry GitHub already formed, so the
hold does both and verifies both are gone:

```text
yoke github merge-queue hold ITEM --json
```

It reports `held` only from that readback; `already_landed` or
`landed_during_hold` names the commit GitHub actually merged, and anything else
leaves the candidate live and says so. Nothing re-arms on its own — correct the
lane, commit, re-run the verification gate against the new candidate, then
re-run `yoke merge item`.

## Read the close-out block, not the exit code alone

Every invocation prints an explicit `[close-out]` outcome block on stderr,
beside the phase markers, while stdout stays the JSON envelope. Its first line
is the verdict — `PREFIX-N closed: done`, `already closed`,
`not closed: landing pending`, or `not closed` with the blocker — and the lines
under it name only what that run confirmed: whether the evidence record now
holds this invocation's `--result` / `--verification` text, and what a live
holder read says about the work claim. Read that block rather than inferring
the outcome from exit 0.

Every way either route ends is named, and none of them is silence:

- **merged** — exit 0. That same command already recorded the evidence and
  closed the item out in this turn; continue at the guardrail-denial report in
  [`close-out.md`](close-out.md). An envelope carrying
  `result: landing_already_recorded` is the same outcome reached by another
  close-out first (a second watcher on the same pull request): the item is
  `done` with its merge identity recorded, the envelope names the session that
  recorded it, and nothing remains to do — do not acquire a claim or transition
  the item again.
- **landing stopped** — exit 9, naming what GitHub reported and the recovery:
  usually rebase the lane onto the base branch, re-run the verification gate,
  and re-run the same command, which re-arms it. Re-running is safe — it
  converges on the merge if one happened meanwhile.
- **a required check already red** — exit 1, terminal for this tree. Fix the
  check, re-run the verification gate, then re-run the landing.
- **landing record stale** — exit 9 names `landing_record_stale`, the last
  record/project refresh times, and the control-plane GitHub recovery. Do not
  substitute local polling; report the blocker with the named repair step.
- **wait budget exhausted** — exit 9 with the last observed reading and the
  exact resume command. Do not re-arm blindly and do not stop quietly: stamp
  `yoke sessions touch --mode parked --reason "<observed landing state>"`, then
  end the turn with a `HUMAN_GATE` report naming the pull request, that reading,
  and the resume command. The item stays non-terminal and the claim stays held,
  so the seat or operator resumes exactly where this left off.

`--wait` returns immediately with a terminal failure when the pull request's
required checks have already concluded red and nothing is in flight for that
head sha; the wait budget applies only while checks or the train are genuinely
pending.

## When deployment posture is selected

Merge first without closing out, so the item-bound deployment can run against
the recorded merge identity. Skipping the status flip does not skip the review
stage: admission still requires the item to have reached it, which the verify
phase already did:

```text
yoke merge item ITEM --skip-status --json
```

Start item-bound delivery for the returned `merge_sha`, run it through the
project executor, and wait for `succeeded`. Use the selected control-plane
connection for ordinary external delivery, including HTTPS. Only when the
target is that control plane's own serving API should you switch to the paired
local `*-db-admin` connection named by the executor's refusal:

```text
yoke --env <control-plane> deployment-runs start-for-item ITEM \
  --release-lineage <merge-sha> --json
```

Next: [`close-out.md`](close-out.md).
