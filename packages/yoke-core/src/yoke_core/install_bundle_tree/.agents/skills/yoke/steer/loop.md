# /yoke steer — standing loop

Run this loop after each steering acquire atomically holds a project seat and
its paired strategy-doc lock. Each pass reads every claimed document first, then keeps it current.

Do not invoke `/yoke feed`.

## Wake sources

- A delivered session message (acknowledge first, then act).
- A periodic frontier check when no message is waiting.

Read [watching.md](watching.md) completely and start or reattach the standing
fleet watcher on every harness and CLI/desktop surface. Its returned wait mode
selects the native subscription or active tool stream. Ordinary questions do
not stop this loop; answer them while authorized coordination continues.

<!-- BEGIN GENERATED: harness-wake-capability -->
Wake capability is a manifest fact, not prose. Source of truth:
`agent_wake` in `runtime/harness/<harness_id>/manifest.json`, rendered from
`yoke_contracts.harness_wake_capability`. Change the contract and re-render; never
restate one of these facts on a document's own authority.

- `claude-code` — idle wake: supported (`Monitor`); timer wake: supported (`ScheduleWakeup`). Verified on claude-cli.
- `codex` — idle wake: none; timer wake: none. Verified on codex-cli.
- `cursor` — idle wake: supported (`notify_on_output`); timer wake: none. Verified on cursor-cli.
<!-- END GENERATED: harness-wake-capability -->

Check live mode before each resumed pass: an explicit `parked` pause remains
until the operator resumes coordination. Only then stamp
`yoke sessions touch --mode steer` if needed. After compaction or resume,
reattach the running watcher or re-arm it when absent, respecting that pause.

## Pass

### 1. Read the standing plan first, then the scope frontier

```text
yoke strategy doc get {SLUG} --project {_project}
```

Extract its next steps and standing decisions before reading the live DB frontier:

```text
yoke charge schedule --project {_project} --json
yoke claims steering list --project {_project} --active-only --json
```

The document wins on intended scope, priority, order, and constraints; the DB wins
on live item status, claims, dependencies, and runnable eligibility. A DB-gated item
waits and refreshes the doc; a DB-runnable item absent from or ordered differently
by the doc does not silently become next. Reconcile through registered surfaces
before acting; escalate only for a reserved human decision.

`charge.schedule` is a frontier **read**, not dispatch or feed. Record runnable items, dependency gates, and claims; write material movement into the doc (step 7).

When a blocker merges and an activation gate clears, explicitly wake the
waiting dependent; activation dependencies do not send their own go-signal:

```text
printf '%s' "GO PREFIX-N: dependency gate cleared; resume the routed leg" | yoke say --item PREFIX-N --stdin
```

#### Negative-space checks — first, every periodic pass

Positive wake events are not enough. Failures arrive as silence, and the
fleet report is the detector for them: it is composed server-side and
rides hook context. On every pass **read the report you were given** before
consuming events, messages, or worker reports. A harness may persist that
context to a file and show only a preview from the top — open the file, not
the preview. Between wakes, pull (omit `--project`):

```text
yoke steering report get
```

The report already answers, from live control-plane state, every check that
used to be a hand query here — one section per finding, each listed below
with what to do about it, and idle holders keyed on `last_tool_call_at`
rather than any liveness label. Do not re-run those queries by hand: a seat
that did burned a pass rediscovering what the report on screen already told
it. A section with nothing to say prints nothing, so a short report is a
quiet fleet rather than a broken detector: failures are silences, and the
report scans them every pass.

Read [fleet-findings.md](fleet-findings.md) completely and act on every
finding before continuing this pass.

Two things the report deliberately does not do, so do them yourself:

- **Re-verify ownership immediately before launching or reclaiming.** The gap
  between the report's composition and your action is one more claim handoff
  window. Observed: a sweep hit that window and staffed a second worker onto
  a healthy item.

  ```text
  yoke claims work holder-get PREFIX-N
  ```

- **Set the hold flag on work you are holding on purpose, and recheck it
  every pass.** The report excludes frozen and operator-blocked items rather
  than guessing intent from age, so an item you have parked reports as
  available until you say so with `yoke items freeze PREFIX-N` or `yoke
  items block PREFIX-N --reason TEXT`; cancel (not freeze) work that will
  never resume. Keep only current blockers or explicit operator holds, not
  filing notes — unblock and resume the moment the reason clears.

The dashboard session card carries one primary status in the identity line:
`active` under a minute of activity, `idle` once quiet, confirmed `stale`
when the server has classified it, and `possibly stale` only while still
server-active past the window with claims and no wait or probe. A
claim-holding card's primary becomes `waiting` or `probed` when those facts
explain the quiet. Age, relay, and latest-message stay labelled subordinates
and never restate that status word. The server's classification against the
executor-aware TTL (1440 minutes on this surface) solely decides alive versus
stale, so an `idle` card with a 6h activity age can still be a session the
control plane counts. The age says how long it has been quiet.

### 2. Consume worker reports

Item-addressed messaging is the default. The server resolves the live
holder of a claim; do not hand-copy or expand a session UUID.

```text
printf '%s' "$BODY" | yoke say --item PREFIX-N --stdin
```

Also `--epic-task ITEM:N` and `--process KEY`. `--session UUID` is the
fallback for a claim-less recipient only (this itemless steerer is one).
No Yoke surface shortens a session id, so a short one did not come from Yoke: never pad, complete, or expand one by hand.

```text
yoke messages list --json
```

For each authenticated inbound message: acknowledge immediately, then assign
a substantive disposition before switching topics or ending this pass: act
now, record the exact dependency/hold in existing item and strategy state, or
surface the reserved operator decision. Acknowledgement is receipt, never
completion. Apply only what the report justifies. Carry unfinished actions in
CURRENT-PLAN (or the explicitly claimed standing plan), with the message id,
item, owner, next action, and exact release condition, so compaction and a
seat handoff cannot erase work whose mail is already acknowledged.

```text
yoke messages acknowledge MESSAGE-ID
```

Typical report body: `DONE PREFIX-N <one-line summary>`. The PREFIX-N in
that heading is the report identity: it must name work the sender holds or
has released, not another live claim. When a
DONE envelope arrives, treat it as a prompt to verify, not proof of
completion. Workers can finish without sending one, too. Confirm both the
item status and the latest matching claim's `release_reason=completed`:

```text
yoke items detail get PREFIX-N --json
yoke db read "SELECT release_reason FROM work_claims WHERE target_kind = 'item' AND scope->>'item_id' = '{BARE_ITEM_ID}' ORDER BY id DESC LIMIT 1"
```

When those authorities show the steering-scoped item is complete:

1. Update item state, dependencies, or gates through the registered item
   surfaces the report actually requires — never invent a status change.
2. The worker should already have followed
   [`worker-lifecycle.md`](worker-lifecycle.md) rule 5 and self-ended after
   reporting. Routine completion never calls `yoke sessions terminate`;
   reserve termination for an unresponsive worker or cleanup.
3. Write the close-out into the doc.

#### Revive starved workers

A quiet `claude-cli` worker is dead: Claude heartbeats advance on tool calls.
Send an item-addressed wake first:

```text
printf '%s' "WAKE PREFIX-N: resume the assigned routed leg and report status" | yoke say --item PREFIX-N --stdin
```

Never hand-wake a parked CLI worker: with no idle wake it escalates to a relay
wake on the first pass. A desktop session is nobody's to resume; its operator
types in that chat to deliver it. Read `state='pending'`, `injection_count=0`:

```text
yoke db read "SELECT session_id,state,injection_count,wake_escalation,created_at FROM session_message_recipients WHERE session_id = '{SESSION_ID}' AND state = 'pending' AND injection_count = 0 ORDER BY created_at DESC"
```

A `cursor-cli` row with no `wake_escalation` past the grace window is what the
bridge is still for; resume that stuck session directly:

```text
cursor-agent --resume <session-id> --print --output-format json --workspace <dir> --trust '<instruction>'
```

A run of deaths within a few tool calls on one installed, signed-in surface is
vendor quota or credits exhausted. Rebalance new lanes onto the other surfaces
until it recovers, then restore the steady-state balance.

### 3. Write the strategy document itemless

The coordinator holds no work item. The claimed doc is the durable write target
for plan-level progress: objective, frontier, decisions, gates, and dead ends.
Edit through `strategy render`, `strategy ingest`, or `strategy.doc.replace`;
the doc plus the items survive coordinator death.

Item-spec writes are the exception to itemless authority. Hold a temporary
item claim for exactly the registered structured-field write, then release
it immediately:

```text
yoke claims work acquire --item PREFIX-N --reason steering
printf '%s' "$CONTENT" | yoke items structured-field replace PREFIX-N --field <field> --stdin
yoke claims work release --item PREFIX-N --reason "steering spec write complete"
```

### 4. Hand a chunk to an executor

Read and follow [`blitz-handoff.md`](blitz-handoff.md) completely whenever a
strategy-document chunk needs an executor. It owns the link, lock-release,
dependency, launch, and automatic document-archive boundary.

### 5. Staff unpicked runnable work

Runnable work that sits unclaimed is this seat's to staff; nothing else
does it. Work this seat files is staffed in the same pass, as soon as it is
runnable; the report is not its trigger. Everything else runnable and
unclaimed reaches you through the available list of the report you already
read above (`yoke steering report get` between wakes).

Launch per [`worker-lifecycle.md`](worker-lifecycle.md) — item-bound and
CLI-only, never a hand-rolled spawn and never `/yoke do`.

Before switching topics or ending any pass, reconcile **all runnable scoped
work** against the standing plan and live schedule. Verify current ownership,
launch or restaff each authorized unclaimed item, unblock and resume cleared
dependents, and record an exact dependency, hold, or reserved decision for
anything unfinished. Reconcile every seat this session holds; a document seat
covers its linked items, while a project seat covers the project. A watcher
signal is a prompt to read that scope authority, never permission to staff
outside it. Keep independent work moving while one item waits.

### 6. Deploy merged work in batches

Workers merge but never create or dispatch deployment runs. The steerer owns
batch delivery through the **prod control-plane** db-admin connection, even
when the target environment is stage.

**Take the project's deploy lock before the first run and hold it through the
whole pair.** Creating a run and executing one both refuse without it, so one
seat drives a project's deployments and a stage promotion cannot overtake the
production promotion it precedes:

```text
yoke claims coordination-claim acquire --project {_project} --key DEPLOY:{_project} --reason "driving the release pair"
```

Pin one source SHA and use that same SHA for stage and production:

```text
yoke --env <cp>-db-admin deployment-runs create {_project} {FLOW} --environment {ENV} --project-repo-path {CHECKOUT} --source-ref {PINNED_SHA}
yoke --env <cp>-db-admin deployment-runs add-item {RUN_ID} PREFIX-N
yoke --env <cp>-db-admin deployment-runs validate-composition {RUN_ID}
yoke --env <cp>-db-admin watch deploy -- {RUN_ID}
```

Repeat `add-item` once for every item in the batch, using its public reference.
Do not start execution unless `validate-composition` accepts the complete
membership. These commands preserve the same deploy lock and refuse items from
another project, incompatible flow bindings, or enrollment after the run has
left `created`.

Retry from the recorded run instead of silently creating unrelated lineage:

```text
yoke --env <cp>-db-admin deployment-runs create {_project} {FLOW} --retry-of {RUN_ID}
```

After the batch succeeds, finish every item parked at its release boundary.
Briefly acquire that item's work claim and run its done ceremony:

```text
yoke claims work acquire --item PREFIX-N --reason "steering done ceremony"
yoke watch merge done-transition -- PREFIX-N
```

Release the claim only if the ceremony did not already release it. An item
parked at release still holds path claims and blocks dependents until this
ceremony finishes.

Then release the deploy lock, so the next seat can drive:

```text
yoke claims coordination-claim release --project {_project} --key DEPLOY:{_project} --reason "release pair complete"
```

Nothing reclaims that lock automatically. After confirming the pipeline settled,
a signed-in human outside any harness session runs `yoke coordination-claim
release --project P --key DEPLOY:P --claim-id N --holder-session-id S --reason
"..."`; HTTPS/local authority, exact-holder refusal, reason, and WARN audit apply.

### 7. Keep the document current

After every material change — frontier movement, gate decision, launch,
escalation, dead end, report close-out — write it into the claimed doc
through the registered strategy surfaces. The doc is coordinator state,
not a wrapup artifact.

Maintain one dated section with this exact heading, refreshing or replacing
it at the next steering handoff rather than accumulating stale snapshots:

```text
## Live status — steering snapshot (refresh or replace on next steering handoff)
```

It carries current seat holdings, in-flight lanes, deploy-batch state, the
dependency-edge queue, any live outstanding operator action and what it
blocks, and the recipes currently in force. A successor must be able to
cold-start the scope from the claimed document alone.

### Operator reminders in every reply

Every operator-visible reply/turn, including an answer to an ordinary
question, repeats **all live outstanding operator actions**. State each item,
the specific required action, and what it unblocks. No most recent blocker
hides another. Keep repeating each action until resolved or explicitly muted;
record the resolution or mute in the standing plan. Fold these reminders into
the normal response, never a separate wake or turn just to nag.

Before each reminder, verify the actual authority: the live item gate,
claim/lock, refusal, or decision record. If a system failure caused the hold,
correct the attribution and pursue its repair; do not repeatedly ask the
operator to perform an action the system owes. Preserve the complete reminder
set, its evidence and unblock conditions in the existing standing plan's live
status section so it survives compaction and handoff. Reconcile resolved and
muted entries before replying; ordinary questions never waive this duty.

### 8. Escalate only human decisions

Escalate to the operator when the loop cannot choose: conflicting reports, a
scope that needs a new project, a lock it cannot release without destroying
in-flight work, or any decision the operator reserved. Present the decision,
the evidence, and the recommended option, then **wait**. Do not guess. Do not
implement. Do not file a substitute item to dodge the gate. Everything else
continues autonomously.

## Stop

A clean stop is wrapup in `SKILL.md` step 5: release the steering-scope claim,
which releases its paired document lock too. An abandoned coordinator is
reclaimed by the stale sweep; do not treat that as a successful wrapup.
