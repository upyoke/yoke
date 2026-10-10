# Dash — confirm the verified tree and land it

Re-survey every actual touched file immediately before merge.
Contacts stay advisory: independent proceed, ordered wait for landing proof
and re-survey, unresolved release/name holder/path/evidence.
Require clean HEAD matching every accepted SHA-bound verdict.
Edit/commit/amend/rebase invalidates affected proof. No hand merge,
force-push, CI bypass or landing around a registered claim.

## Exact human candidate review

Selected merge_candidate_review refuses before arming/enqueue/merge and
names the reviewer's open decision request. The work-holder session cannot
approve it, clear posture or impersonate another session. Report the request
id, checkpoint and wait; no retry loop. Any later commit needs new clearance.
`yoke merge-review candidate evaluate ITEM --commit SHA` is read-only.
Only an authorized independent reviewer resolves the named request.

The merge may itself dispatch/adopt postrebase CI with a durable wait.
Continue its native handle to exit. If interrupted, rerun the same command to
adopt the exact-commit run, not another suite. A failed wait registration names
its warning; never promise an unregistered wake or poll GitHub yourself.

## Wake-routed wait

The first landing call arms/queues the PR and returns landing_pending only
after GitHub readback proves armed/queued, still eligible/mergeable and no
required checks already red. Armed before queue entry is ordinary.
Failed arming, ineligible PR or a concluded red check refuses by name.

A relay-launched session arms the landing and stops. Report by naming the pull
request, whatever you passed as result/verification, and say you are waiting
on landing: a headless command cannot outlive a queue landing. Treat its
recorded pending landing as a legitimate stop. The control-plane landing
notice wakes you to rerun the same merge with result/verification.

**Every other session waits.** The shape is resolved from the calling session's
manifest wake capability, never from who opened the session, its executor name,
or whether Yoke can reach it over a relay. A native idle-wake primitive preserves
the background subscription; a harness with no or unverified idle wake keeps
the wait in-turn. Thus a desktop conversation waits exactly as its CLI sibling
does. A relay-launched session takes the arm-and-stop handoff above.

Ask the watcher for its safe invocation:

```text
yoke watch merge --print-streaming-pair merge-item -- ITEM --wait --result "<result>" --verification "<proof>"
```

That call only prints: it merges nothing, arms nothing; run the printed command
exactly once. `background-wake` means the caller's harness can resume an ended
turn and uses its bound background/subscription pair. `in-turn` means the printed
command is a single foreground invocation. No later completion notice is
expected. The wrapper's four-fact landing readback (armed, queued, eligible,
required checks) never needs a hand-authored `gh` poll loop.

For Claude in-turn waits, set the Bash tool's `timeout` to `600000` so the harness
does not move the call to a background task. If it moves the call anyway, the
command is still running: continue that same call through the background task's
output. Reading that output continues the call; only ending the turn kills the
watcher. Never launch another copy beside it.

The wrapper observes through control-plane merge_queue.landing.observe with
one project-wide GitHub sweep per cadence and streams changed durable records
and an exit sentinel. The waiting machine issues no `gh`, GitHub, or `git fetch`
read loop. Named outcomes follow; none of them is silence.
A tunnel_busy sibling owns authority lifecycle: leave it running and retain
this invocation through the bounded replacement window.
Read readiness through `yoke github merge-queue readiness ITEM --json`;
null arming with queue-entry=AWAITING_CHECKS can mean consumed and in flight,
not cleared.

## Hold before a correction

Every publish refuses while its PR is live armed/queued. Clear auto-merge and
queue entry together with verified readback:

```text
yoke github merge-queue hold ITEM --json
```

Only held proves both gone. Already-landed/landed-during-hold names the actual
merge; other answers leave it live. Nothing auto-rearms.
Correct, commit, reverify the new candidate and merge again.

## Read the explicit close-out outcome

Stderr's [close-out] block reports actual status, stored result/verification
and holder fact beside stdout's envelope. Exit0 alone is not done.

- **merged** — exit 0: the boundary closed the item out in this turn, or
  landing_already_recorded names its receipt. Read status/identity; done needs
  no new claim/transition. Continue denial reporting.
- **landing stopped** — exit 9: follow named recovery, rebase the lane onto the
  base branch and re-run the verification gate before the same merge command.
  It converges on the merge if one happened meanwhile; never discard landed state.
- **a required check already red** — exit 1, terminal for this tree: fix,
  commit/reverify, then rearm. A cancelled/not-started check has no verdict;
  rerun same-head landing for replacement without a fabricated fix.
- **landing record stale** — landing_record_stale, exit 9: report last
  record/project refresh times and named control-plane recovery. Do not
  substitute local polling.
- **wait budget exhausted** — exit 9: checkpoint PR, last observed reading and
  exact resume; `yoke sessions touch --mode parked --reason "<observed landing state>"`.
  Report HUMAN_GATE. The item stays non-terminal and the claim stays held.

Wait budget only covers genuinely pending checks/train; a concluded red head
with nothing in flight returns immediately. Never rearm blindly after timeout.
Checkpoint and park with observed state before that legitimate stop.

## Selected deployment posture

Merge first with recorded identity; skip-status never skips review admission:

```text
yoke merge item ITEM --skip-status --json
```

Delivery must use the selected item-bound project flow for returned merge_sha,
with a run succeeded before completion.
Read [delivery authority](../../../../.yoke/docs/reference/agent-rules/delivery.md)
first and acquire DEPLOY:P before creating/executing any run, releasing after.
A steering-batched worker follows its mandate and retains release wait; it
does not start an independent run. An authorized driver uses:

```text
yoke --env <control-plane> deployment-runs start-for-item ITEM --release-lineage <merge-sha> --json
```

Ordinary delivery uses its connected authority, including HTTPS.
Serving-API self-deploy refusal routes to the control-plane operator with the
named recovery. Follow the project's executor/watcher to actual success.
Next: [close-out.md](close-out.md).
