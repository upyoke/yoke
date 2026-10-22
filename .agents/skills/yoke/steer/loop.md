<!-- BEGIN GENERATED: harness-wake-capability -->
Source: `agent_wake` in `.yoke/harness/<harness-dir>/manifest.json`, from `yoke_contracts.harness_wake_capability`.

- `claude-code` — idle wake: supported (`Monitor`), each subscription ending within 30 minutes (`timeout_ms`); re-arm the same tail on the expiry notice; timer wake: supported (`ScheduleWakeup`). Verified on claude-cli.
- `codex` — idle wake: none; timer wake: none. Verified on codex-cli.
- `cursor` — idle wake: supported (`notify_on_output`); timer wake: none. Verified on cursor-cli.
<!-- END GENERATED: harness-wake-capability -->


# Steer — standing loop

On resume, reload this phase and reattach or re-arm the watcher. Read Live
Status first; fetch claimed contracts on demand through strategy.doc.get.
Preserve every claimed document's unresolved holds and obligations.

## 1. Plan, frontier, report

```text
yoke strategy doc get {SLUG} --project {_project}
yoke charge schedule --project {_project} --json
yoke steering report get
```

- Follow doc scope, priority and order; read status, claims and eligibility
  from the DB. Handle every finding per [fleet-findings.md](fleet-findings.md).
- Hold work with `yoke items freeze PREFIX-N`; abandon with
  `yoke items cancel PREFIX-N --reason TEXT`.
- An `activation` edge sends no go-signal; after its blocker clears, send
  `GO PREFIX-N` with `yoke say --item PREFIX-N --stdin`.
- If the doc's last curation date is absent or 7+ days old, ask the operator
  to run `/yoke curate`.

## 2. Messages

```text
yoke messages list --json
yoke messages get MESSAGE-ID
yoke messages acknowledge MESSAGE-ID
```

Read and acknowledge full messages; act, hold, or surface decisions this pass.
Workers may finish without mail. Verify `DONE PREFIX-N` means terminal status
and the last claim released `completed`:

```text
yoke items get PREFIX-N status --json
yoke db read "SELECT release_reason FROM work_claims WHERE target_kind = 'item' AND scope::jsonb->>'item_id' = (SELECT item_id::text FROM item_refs WHERE public_ref = 'PREFIX-N') ORDER BY id DESC LIMIT 1"
```

## 3. Staff everything

Only this seat staffs work: [launch](worker-launch.md) every runnable,
unclaimed scoped item this pass.

For specs:

- Blocking cases create release preconditions: a throwaway walk to stop,
  a fixture PR to eject, or short traffic.
- Put real-event or long-wait evidence on the item: "record the next real
  occurrence", outside blocking QA.
- Split missions by machine for parallel host queues; order a small
  cross-machine mission after the single-machine ones.

Take a temporary claim to write:

```text
yoke claims work acquire --item PREFIX-N --reason steering
yoke items structured-field replace PREFIX-N --field FIELD --stdin < CONTENT_FILE
yoke claims work release --item PREFIX-N --reason "steering spec write complete"
```

## 4. Vet before release admission

```text
yoke items detail get PREFIX-N --json
git -C {CHECKOUT} diff {BASE_SHA}...{LANDED_SHA}
```

Route problems to [rework](worker-launch.md#rework), keeping them outside release;
never select `merge_candidate_review`. Follow [release batches](release-batches.md),
including [manual-wake QA](release-batches.md#manual-wake-member-qa).
Failed QA: follow `.yoke/docs/verification/failed-item-qa.md` for correction,
retained-owner waits and retesting.

## 5. Live status

After a change, refresh one section:

```text
## Live status — steering snapshot (refresh or replace on next steering handoff)
```

Carry current seats, owners, blockers, next steps and operator actions.
For conflicts, new scope or reserved decisions, present evidence and a
recommendation, then wait; continue independent work within the gate.
Stop: [close-out.md](close-out.md).
