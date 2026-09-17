# /yoke steer step 5 — close-out, seat hygiene, surface marks

## 5. Close-out: settle, hand off, and release everything held

Release is mark-complete, not silence. A deliberate close-out is a full
shutdown and handoff, not just the steering claim; an abandoned coordinator
is reclaimed by the stale sweep instead. Honor an explicit stop promptly,
then work through this order:

1. **Snapshot state for the successor.** Refresh the strategy document's
   `## Live status — steering snapshot` (see [`loop.md`](loop.md) § "Keep
   the document current") with current runs, workers, and each one's exact
   successor action — a cold-start reader must be able to pick up the scope
   from the document alone.

2. **Stop this session's own watchers and recovery automation.** Stop the
   fleet watcher through its owning tool handle (see
   [`watching.md`](watching.md)); on Codex, remove the `keep steering`
   scheduled task if one is running — a watcher left armed has nowhere to
   deliver its next wake.

3. **Settle or explicitly hand off every active operation before releasing
   the lock protecting it.** A `landing_pending` merge, an in-flight deploy
   batch, or a worker mid-mandate is not release-ready: use its existing
   recovery path (re-run `yoke merge item`, let the deploy batch finish,
   message the worker) or hand it to the successor named above. Releasing a
   lock never settles the operation it guarded.

4. **Inventory every claim and lock this session holds.** No single bulk
   call covers it — read all three:

   ```text
   yoke claims steering list --session-id {SESSION_ID} --active-only --json
   yoke claims coordination-claim list --session-id {SESSION_ID} --active-only --json
   yoke claims work holder-list --session-id-filter {SESSION_ID} --json
   ```

5. **Release every remaining session-owned claim/lock** — never another
   worker's or an item-owned claim. Steering seat first (its paired
   strategy-doc lock leaves with it), then every coordination claim the
   inventory surfaced by name (e.g. `DEPLOY:{project}` — sticky, so it
   survives `--all-mine`), then any remaining work claim:

   ```text
   yoke claims steering release {CLAIM_ID} --reason "steer close-out"
   yoke claims coordination-claim release --project {_project} --key DEPLOY:{_project} --reason "steer close-out"
   yoke claims work release --all-mine --reason "steer close-out"
   ```

6. **Re-verify zero unintended holds.** Re-run the three list calls from
   step 4; each must return empty, or name only what step 3 deliberately
   handed off with its own recorded successor.

If a live operation cannot be settled or handed off safely, stop short of
releasing its lock, name the concrete exception and exact recovery action
instead of reporting a complete close-out. An explicit operator instruction
to release a held lock is authorization on its own; do not ask again.

Then `/yoke wrapup` if the operator asked for a session close. Do not
release the paired strategy document directly while the steering seat is
live; that refusal teaches this paired release instead.

## Seat hygiene (token economics)

- Every wake resends the seat's whole transcript, so cost-per-wake grows
  with transcript length. When the transcript is heavy and the fleet is
  quiet, prefer an orderly handoff — update the strategy doc's Live
  status, release the seats, and let a fresh session cold-start from the
  doc — over dragging a long transcript through every subsequent wake.
- When self-scheduling a wakeup, pick the delay for what is actually
  being awaited and avoid landing just past the prompt-cache window:
  wake densely while genuinely active or rarely with a batched pass —
  the just-expired middle pays full transcript price per wake for
  nothing.

## Surface disable marks

This is a manual circuit breaker, not a state machine. Do not count
failures, auto-trip, auto-clear, or probe on a timer.

When a run of same-surface worker failures carries a vendor-side
signature (quota exhausted, launch path broken on that harness), disable
that `(machine, surface)` and rebalance new launches onto the other
harnesses:

```text
yoke session-control surface-policy disable --project {_project} --machine M --surface S --reason vendor_signature
```

Before re-enabling, run one cheap canary launch on that surface. Clear
the mark only after that canary succeeds:

```text
yoke session-control surface-policy enable --project {_project} --machine M --surface S
```

Escalate to the operator instead of marking when failures are
unclassified. Unclassified failures can be Yoke-side; disabling a
healthy harness for our own bug is the failure mode to avoid. Marks
gate new launches and native-resume spawns only; in-flight sessions
stay up.
