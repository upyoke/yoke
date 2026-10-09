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

## Landing and wait authority

The first landing call arms/queues the PR and returns landing_pending only
after GitHub readback proves armed/queued, still eligible/mergeable and no
required checks already red. Armed before queue entry is ordinary.
Failed arming, ineligible PR or a concluded red check refuses by name.

A relay-launched session takes the recorded arm-and-stop handoff; report PR
and pending landing, then deliberately stop. The landing notice wakes it to
rerun the same merge with result/verification. Other callers' wait shape comes
from the manifest's verified native idle-wake capability, not executor name
or launch origin.

Ask the watcher for its safe invocation:

```text
yoke watch merge --print-streaming-pair merge-item -- ITEM --wait --result "<result>" --verification "<proof>"
```

That prints only; it does not arm, merge or record. Run the returned command
or bound background/subscription pair exactly once. Background-wake expects a
native completion wake only because the mode proved it. In-turn remains a
foreground invocation through exit, with no later wake.
Claude in-turn watchers need the documented 600000 tool timeout; if a handle
still yields, continue that same handle, never launch a second copy or end
the turn over a live watcher.

The wrapper observes through control-plane merge_queue.landing.observe with
project-wide cadence/rate limiting, streams changed durable records and exit
sentinel; no local gh/GitHub/fetch loops.
A tunnel_busy sibling owns authority lifecycle: leave it running and retain
this invocation through the bounded replacement window.
Read readiness through `yoke github merge-queue readiness ITEM --json`;
null arming with awaiting-checks queue entry may mean consumed/in flight.

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

| Outcome | Action |
|---|---|
| merged/closed or landing_already_recorded | Read status/identity; done needs no new claim/transition; continue denial reporting |
| landing pending | Recorded handoff, not completion |
| landing stopped (9) | Follow named recovery, refresh lane/proof and rerun same command; it converges if landing occurred |
| required checks red (1) | Terminal for this tree; fix/reverify then rearm |
| cancelled/not-started check | No verdict, not red; rerun same-head landing to get replacement, no fabricated fix |
| landing_record_stale (9) | Report control-plane refresh/recovery; no local polling |
| wait budget exhausted (9) | Park retaining claim, report HUMAN_GATE with PR/last state/exact resume command |

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
