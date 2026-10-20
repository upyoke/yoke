<!-- BEGIN GENERATED: harness-wake-capability -->
Source: `agent_wake` in `.yoke/harness/<harness-dir>/manifest.json`, from `yoke_contracts.harness_wake_capability`.

- `claude-code` — idle wake: supported (`Monitor`), each subscription ending within 30 minutes (`timeout_ms`); re-arm the same tail on the expiry notice; timer wake: supported (`ScheduleWakeup`). Verified on claude-cli.
- `codex` — idle wake: none; timer wake: none. Verified on codex-cli.
- `cursor` — idle wake: supported (`notify_on_output`); timer wake: none. Verified on cursor-cli.
<!-- END GENERATED: harness-wake-capability -->


# Steer — standing loop

After compaction or resume, reload this phase: discarded context is gone;
reattach the running watcher or re-arm it when absent. Preserve unresolved
holds and obligations from other claimed documents. Never erase that contract
to hit a size target. Routine resume reads only the Live Status checkpoint;
read claimed contract slugs on demand through strategy.doc.get.

## 1. Plan, frontier, report

```text
yoke strategy doc get {SLUG} --project {_project}
yoke charge schedule --project {_project} --json
yoke steering report get
```

- The doc wins on scope, priority and order; the DB wins on live status,
  claims and eligibility.
- Act on every report finding per [fleet-findings.md](fleet-findings.md).
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

Read each full message, acknowledge it, then act, record a hold, or surface
the decision this pass. `DONE PREFIX-N` means verify the item is terminal and its last work claim
released `completed`; workers may finish without mail:

```text
yoke items get PREFIX-N status --json
yoke db read "SELECT release_reason FROM work_claims WHERE target_kind = 'item' AND scope::jsonb->>'item_id' = (SELECT item_id::text FROM item_refs WHERE public_ref = 'PREFIX-N') ORDER BY id DESC LIMIT 1"
```

## 3. Staff everything

Before ending a pass, launch every runnable unclaimed scoped item
([worker-launch.md](worker-launch.md)). This seat is the only staffing path. A spec write takes a temporary claim:

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

Never select `merge_candidate_review`. Problems stay out of the release; route
[rework](worker-launch.md#rework). Then [release-batches.md](release-batches.md),
including [manual-wake member QA](release-batches.md#manual-wake-member-qa).
After a QA failure, confirm the owner started rework or recorded a blocker.

## 5. Live status

After any material change, refresh one section:

```text
## Live status — steering snapshot (refresh or replace on next steering handoff)
```

Carry seats, owners, blockers, next steps and operator actions. Do not copy
historical status sections.

Conflicts, new scope or a reserved decision: present evidence and a
recommendation, then wait. Never guess, implement or file a substitute item
to get past the gate; keep independent work moving. Stop: [close-out.md](close-out.md).
