<!-- BEGIN GENERATED: harness-wake-capability -->
Wake capability is a manifest fact, not prose. Source of truth:
`agent_wake` in `runtime/harness/<harness-dir>/manifest.json`, rendered from
`yoke_contracts.harness_wake_capability`. Change the contract and re-render; never
restate one of these facts on a document's own authority.

- `claude-code` — idle wake: supported (`Monitor`); timer wake: supported (`ScheduleWakeup`). Verified on claude-cli.
- `codex` — idle wake: none; timer wake: none. Verified on codex-cli.
- `cursor` — idle wake: supported (`notify_on_output`); timer wake: none. Verified on cursor-cli.
<!-- END GENERATED: harness-wake-capability -->

# Steer — standing loop

Run only with paired steering/document authority. Routine resume reads only
the Live Status checkpoint; read claimed contract slugs on demand through
strategy.doc.get, never erase contracts to meet a size target. No feed.
Read [watching.md](watching.md) completely and attach every held scope's
manifest-selected stream. Explicit parked pause survives resumes/compaction;
only operator resumption stamps steer/rearms. Ordinary questions continue it.

## 1. Plan, frontier, then negative-space findings

```text
yoke strategy doc get {SLUG} --project {_project}
yoke charge schedule --project {_project} --json
yoke claims steering list --project {_project} --active-only --json
```

Extract next steps/standing decisions first. The document wins on intended
scope, priority, order and constraints; the DB wins on live item status,
claims, dependencies and runnable eligibility. A runnable item absent from
or differently ordered by the doc does not silently become next. Reconcile
through registered authority; DB-gated work waits and updates the doc.
charge.schedule is a frontier read, never dispatch or feed.

### Negative-space checks — first, every periodic pass

Failures arrive as silence; the fleet report is the detector. Read the whole
hook report before consuming events, messages, or worker reports. If persisted
with a preview, open the file, not the preview. Between wakes pull all held scopes:

```text
yoke steering report get
```

Do not re-run those queries by hand. Detectors use last_tool_call_at rather
than any liveness label. A section with nothing to say prints nothing.
These failures are silences. Read [fleet-findings.md](fleet-findings.md) and
dispose of every finding before continuing.

Two things the report deliberately does not do:
- Re-verify ownership immediately before launching or reclaiming: composition
  leaves one more claim handoff window; stale readback can staff a second
  worker onto a healthy item. Read yoke claims work holder-get PREFIX-N.
- Set the hold flag on work you are holding on purpose, rechecking each pass.
  Report excludes frozen/operator-blocked work rather than guessing intent.
  Use yoke items freeze PREFIX-N or block with reason; permanently abandoned
  work uses yoke items cancel PREFIX-N --reason TEXT. Keep only actual blockers/
  operator holds, unblock/resume when cleared.

Since activation dependencies do not send their own go-signal, after verified
blocker merge/gate clearance, explicitly resume the waiting dependent:

```text
printf '%s' "GO PREFIX-N: dependency gate cleared; resume the routed leg" | yoke say --item PREFIX-N --stdin
```

The dashboard session card is a faster read: active for live, parked for
declared wait, confirmed stale only by server, possibly stale while unresolved;
waiting/probed explain a claim holder's quiet. Recency remains subordinate,
not evidence of death. Effective executor TTL is reported data; an active work
claim protects its holder from age reclaim. An idle session can still be a
session the control plane counts. Do not reproduce a machine's numeric TTL.

## 2. Read, acknowledge, dispose

```text
yoke messages list --json
yoke messages get MESSAGE-ID
yoke messages acknowledge MESSAGE-ID
yoke inbox list
```

List/excerpt decides what to open, never disposition. Read each authenticated
full message, acknowledge immediately, then assign a substantive disposition
before switching topics or ending this pass: act now, record the exact
dependency/hold, or surface the reserved operator decision. Acknowledgement
is receipt, never completion. Carry unfinished actions in CURRENT-PLAN or
the claimed standing plan with message id/item/owner/next step/release condition.
Inbox decisions are part of this same pass.

Item-addressed messaging resolves live claim holder; also epic-task/process.
Session UUID is fallback only for claim-less recipients. Never reconstruct
an abbreviated UUID. Substantive peer requests copy steering; see worker-launch.

```text
printf '%s' "$BODY" | yoke say --item PREFIX-N --stdin
```

DONE PREFIX-N: that heading is the report identity, naming sender-held/released
work. DONE prompts verification, not completion. Verify terminal item state
and latest matching release_reason=completed; workers may finish without mail:

```text
yoke items get PREFIX-N status --json
yoke db read "SELECT release_reason FROM work_claims WHERE target_kind = 'item' AND scope::jsonb->>'item_id' = (SELECT item_id::text FROM item_refs WHERE public_ref = 'PREFIX-N') ORDER BY id DESC LIMIT 1"
```

Apply only justified item/dependency/gate writes, snapshot completion, and let
worker self-END. No routine termination; reserve it for proven unresponsive,
restaff or cleanup. Quiet/exited between turns is not dead. Send an item
message first. For a report naming an owed stuck wake, read machine evidence
then use registered recovery, never direct native resume:

```text
yoke session-control evidence get --session SESSION-ID
yoke session-control session wake --item PREFIX-N --prompt "Resume the assigned routed leg" --json
```

Moving delivery/wake_in_flight waits; meter_exhausted needs deliberate restaff
with headroom; operator_wake_required needs that desktop operator's prompt.
No surface-disable mark for unclassified failure. Preserve receipts/recovery.

## 3. Write plan state and staff every authorized item

The claimed doc is the durable write target for plan-level progress, through
registered strategy render/ingest/replace. Read chosen command's help and the
project-configuration function catalog. Item spec writes alone take a temporary
item claim for exactly that structured write, then release:

```text
yoke claims work acquire --item PREFIX-N --reason steering
printf '%s' "$CONTENT" | yoke items structured-field replace PREFIX-N --field FIELD --stdin
yoke claims work release --item PREFIX-N --reason "steering spec write complete"
```

Follow [blitz-handoff.md](blitz-handoff.md) for document chunks. There is no second staffing path. Runnable
unclaimed work is this seat's to staff; nothing else staffs it. Filing and
staffing happen in the same pass once runnable. Follow worker-lifecycle and
its one registered CLI launch path. Before switching topics/ending a pass,
reconcile all runnable scoped work for every held seat: verify live ownership,
launch or restaff each authorized unclaimed item, unblock and resume cleared
dependents, record exact hold/dependency/reserved decision for the remainder.
A watcher finding is no authority outside the seat; keep independent work moving.

## 4. Vet before release admission; batch delivery

Worker gates land immediately; steering never selects default prelanding
merge_candidate_review. Vet exact diff/evidence as soon as possible and always
before run admission, not DONE summary:

```text
yoke items detail get PREFIX-N --json
git -C {CHECKOUT} diff {BASE_SHA}...{LANDED_SHA}
yoke qa requirement list --item PREFIX-N --json
```

Unresolved vetting problems stay out of release. Route correction to the
holder; lifecycle transition needs its claim. No takeover of a live lane.
Unheld rework follows worker-launch's acquire/transition recipe, fixes the
same item, re-verifies/re-lands/re-enters release. Read
[release-batches.md](release-batches.md) before composition/execution.

## 5. Preserve current snapshot and verified reminders

After material frontier/gate/launch/report/escalation/dead-end change, refresh
one dated section rather than accumulate history:

```text
## Live status — steering snapshot (refresh or replace on next steering handoff)
```

Carry objective/standing constraints/seat holdings/in-flight owners/blockers/
next steps/evidence. Preserve older unresolved obligations until reconciled;
drop superseded snapshots, not contracts. Do not paste full results.

Every operator-visible reply/turn repeats all live outstanding operator actions:
item, the specific required action, and what it unblocks, until resolved or
explicitly muted. ordinary questions never waive this duty. Fold into normal
reply, never a separate wake or turn just to nag. Before each reminder verify
the actual authority (gate/hold/refusal/decision). If a system failure caused
the hold, correct the attribution and pursue repair. Preserve the full reminder
set/evidence/unblock conditions in the standing plan's live status section;
reconcile resolution/mute before replying.

## Escalate only human decisions

Conflicting reports, new project/scope, unsafe protected lock or reserved
decision: present evidence/recommended option and wait. Do not guess, implement
or file a substitute item to dodge the gate. Continue independent authorized
work. Explicit stop follows [close-out.md](close-out.md); no abandoned lock or
claim is settled by silence.
