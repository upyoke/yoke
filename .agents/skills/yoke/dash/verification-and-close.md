Read [`implementation-and-verification.md`](implementation-and-verification.md)
completely and finish its execution, committed-tree verification, and lifecycle
transition before continuing with the merge sequence below.

### 6. Confirm the verified tree and merge

Immediately before merge, resolve the exact touched set again and replace the
survey with every actual file:

```text
yoke direct-workflow dash survey ITEM --path <actual-file> [--path <actual-file> ...] --json
yoke direct-workflow dash survey ITEM --no-changes --json  # genuine no-change only
```

Read any reported contacts as advisories here too; a recorded overlap does not
itself prevent merge. Proceed when the edits are independent. For
order-dependent work, wait for the holding work to land (merge receipt,
merged_at, or git ancestry — not status) and re-run the survey;
for an unresolved contact, release the work claim and present the path, holder,
and evidence to the operator. Then require a clean worktree whose HEAD is the
tree named by every passing SHA-bound verdict. Any intervening edit, commit,
amend, or rebase invalidates the old verdict: commit the final tree and rerun the
affected case. Do not merge by hand, force-push, bypass CI, or merge around a
registered claim.

### 7. Merge, record evidence, and finish

Merge-queue projects use one watcher invocation whose safe wait shape is
resolved from the calling session's manifest wake capability and current
control-plane reachability. Never choose the route from who opened the session,
its executor name, or its launch origin. A verified wake route preserves the
background subscription; no route, or an unknown answer, keeps the wait in the
current turn. Ending an unreachable caller on `landing_pending=true` can leave
the branch landed and the item at `reviewing-implementation` with nobody to
close it out.

Either way the first call opens / rebases / arms the pull request and returns
`landing_pending=true`, which means GitHub itself reported that it holds the
landing — armed or already queued, still mergeable, and with none of its own required checks already
red — read back rather than inferred from the arming request succeeding.
GitHub creates the queue entry only once those checks pass, so
armed-and-not-yet-queued is the ordinary state here; an arming that never
took, a pull request that is no longer mergeable, and one whose required
checks have already concluded red each refuse instead and name which of
those four it saw. A red required check refuses before anything is armed,
and names the check and its run.

**Reachability-routed wait.** Pass `--wait` through the merge watcher wrapper.
On each documented cadence the waiting client calls
`merge_queue.landing.observe`. The server rate-limits concurrent callers to
one project-wide GitHub sweep per cadence, refreshes every pending landing,
and returns this lane's durable record. It preserves the same four-fact landing
readback (armed, queued, eligible, required checks) as structured pull-request
state, queue holding, named queue-entry state, merge-when-ready state, head SHA,
failed checks, and refresh/change times. The waiting machine issues no `gh`,
GitHub, or `git fetch` read loop. Landing-complete/stopped record changes still
use the existing explicit session wake for a detached holder. The wrapper
streams changed records and writes the exit sentinel that ends the follow; it
never needs a hand-authored `gh` poll loop:

```text
yoke watch merge --print-streaming-pair merge-item -- ITEM --wait \
  --result "<what changed>" --verification "<checks and evidence>"
```

Read the wrapper's `wait_mode` and reason.

- `background-wake` means the caller has a verified route. The selector exits
  after printing the bound background command and subscription; run that pair
  exactly once on the long-command surface your harness rules name. A
  completion wake is expected only because the mode line recorded that route.
- `in-turn` means the same invocation is already holding the foreground wait
  and will not return until landing finishes. No later completion notice is
  expected.

For a separate point-in-time check, run `yoke github merge-queue readiness
ITEM --json`. It reads the target branch's named queue entry with arming, so
null arming plus `queue-entry=AWAITING_CHECKS` means consumed and in flight,
not cleared. A retried invocation publishes any new local lane commits before
the queue is re-armed; it refuses with exact force-with-lease recovery rather
than report a SHA that origin does not yet hold.

Every way either route ends is named, and none of them is silence:

- **merged** — exit 0. That same command already recorded the evidence and
  closed the item out in this turn; continue at the guardrail-denial report
  below. An envelope carrying `result: landing_already_recorded` is the same
  outcome reached by another close-out first (a second watcher on the same
  pull request): the item is `done` with its merge identity recorded, the
  envelope names the session that recorded it, and nothing remains to do —
  do not acquire a claim or transition the item again.
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

When deployment posture is selected, merge first without closing out, so the
item-bound deployment can run against the recorded merge identity:

```text
yoke merge item ITEM --skip-status --json
```

Start item-bound delivery for the returned `merge_sha`, run it through the
project executor, and wait for `succeeded`. Create requires the same-universe
owner-only local-postgres env (not the HTTPS product plane) — the same
`*-db-admin` connection execute uses:

```text
yoke --env <control-plane>-db-admin deployment-runs start-for-item ITEM \
  --release-lineage <merge-sha> --json
```

Otherwise issue the merge-and-close-out command. Non-queue projects and an
explicit `--wait` finish inline; the default queue route follows the handoff
above. The operation resolves the touched files from the branch itself, so no
path list is needed. Dash close-out is
evidence-gated on this same command — pass `--result` and `--verification`
even when the merge queue already landed the branch. Do not substitute
`yoke lifecycle transition --to done`; that path cannot restore the work
claim the landing handoff retains.

```text
yoke merge item ITEM \
  --result "<what changed or was learned>" \
  --verification "<checks and evidence>" \
  --json
```

Add `--no-changes` for a genuine no-change result. When the merge is already
recorded and only the close-out remains — after a deployment run, after
approval, or after a queue landing that has not reached `done` — re-run the
same merge command with `--result` and `--verification`. It restores the
work claim close-out needs and records evidence if the merge identity is
not yet on the item. Do not hand-run `lifecycle.transition --to done` for
Dash close-out.

When approval-on-done is selected, the terminal transition creates the owner
decision request without moving the item. Let an authorized owner resolve it,
then retry the transition. A successful standalone merge (or the terminal
transition it drives) may already release the item work claim and remove the
registered Dash worktree lane, then sweeps lanes earlier landings on this
machine preserved: the envelope's `lane_sweep` names what it removed and kept
(with the reason), and a refusal on the item's own lane is recorded as a
`LandedLanePreserved` event. Only release when a claim remains, or when
exiting before merge:

```text
yoke claims work release --item ITEM --reason "Dash completed"
```

Skip that call when merge or `done` already released the claim. Do not treat
an already-released claim as a close-out failure.

When a report to the steering seat is still owed, send it BEFORE that
release. `yoke say --steering` addresses the seat covering the item you hold,
and falls back to the item you last held in this session, so the report
resolves either side of close-out; sending first keeps the live claim as the
address. One terminal report per session and item reaches the seat once, so a
reworded retry deduplicates rather than arriving twice. A steering-LAUNCHED
session sends nothing here at all — its turn-end text is already that report.

**Surface this session's guardrail denials.** After evidence is recorded,
report this episode's PreToolUse denials. Close-out reports; it does not block.
An empty result is silence: say nothing extra.

Read `session_id` from registered `sessions.identity`
(`yoke sessions identity`); do not invent it. `--session` filters
`events.session_id`. Do not pass `--session-id` — that flag overrides
caller identity. Then run registered `events.query.run`:

```text
yoke events query --session SESSION_ID --event-name HarnessToolCallDenied --current-episode --json
```

When `result.elided_prior_episode_rows` is present, this session crossed
an episode boundary mid-Dash — a sleep, a reload, a brief disconnect —
and that many denials sit in the previous episode. Re-run the same query
without `--current-episode` and report the whole session's denials. An
empty `rows` beside a non-zero count is not a clean run.

When `result.rows` is non-empty, print a short list of each row's
`check_id` and `command_snippet` from `envelope.context.detail` (parse
`envelope` when it is a JSON string). File a field-note for any denial
not already recorded, or state why none is warranted:

```text
yoke ouroboros field-note append --kind observation --evidence '...'
```

Do not correlate denials to field-notes in storage. Visibility is the
entire ask.

### Laneless and evidence-only close-out

Two closes record no merge SHA, and both are first-class rather than a
bypass. A genuine no-changes finding edited nothing:

```text
yoke direct-workflow dash evidence ITEM --result "<account>" \
  --verification "<what you observed>" --no-changes --json
```

An item whose pinned workflow delivers merge-free — `worktrees=none`,
`delivery=merge_free`, the floor Task shape — did change things, and
names them as the observed changes:

```text
yoke direct-workflow dash evidence ITEM --result "<account>" \
  --verification "<what you observed>" --path notes/readme.txt --json
```

Do not reach for `--no-changes` to skip the SHAs on a laneless item that
did change files: the floor rung comes from the item's own delivery
policy, so the SHAs are already optional and `--no-changes` would record
the wrong fact. A merging workflow that omits its SHAs is refused, and
the refusal names both routes.

Task items have no `reviewing-implementation` stage. Close
`implementing` → `done` once the attestation is recorded:

```text
yoke lifecycle transition ITEM --from implementing --to done \
  --reason "Floor attestation recorded"
```

Outward-action approval gating is a future seam; do not invent one here.
