# /yoke steer — standing loop

Run this loop after one steering acquire atomically holds the project seat and
paired strategy-doc lock. Each pass reads the claimed document first, then keeps it current.

Do not invoke `/yoke feed`.

## Wake sources

- A delivered session message (acknowledge first, then act).
- A periodic frontier check when no message is waiting.

<!-- YOKE:HARNESS claude start -->
In a Claude steering session, arm one standing `Monitor` on the fleet-delta
watcher: `yoke watch fleet --print-streaming-pair -- --project {_project}`
prints the pair. Keep the `ScheduleWakeup` fallback of at least 1200 seconds.
<!-- YOKE:HARNESS end -->

Which wake primitives this session actually has is a declared fact, not a
guess. Never teach a harness one it does not declare; a harness declaring
neither runs its passes on message wakes plus its native loop.

<!-- BEGIN GENERATED: harness-wake-capability -->
Wake capability is a manifest fact, not prose. Source of truth:
`agent_wake` in `runtime/harness/<harness_id>/manifest.json`, rendered from
`yoke_contracts.harness_wake_capability`. Change the contract and re-render; never
restate one of these facts on a document's own authority.

- `claude-code` — idle wake: supported (`Monitor`); timer wake: supported (`ScheduleWakeup`). Verified on claude-cli.
- `codex` — idle wake: none; timer wake: none. Verified on codex-cli.
- `cursor` — idle wake: supported (`notify_on_output`); timer wake: none. Verified on cursor-cli.
<!-- END GENERATED: harness-wake-capability -->

Stamp `yoke sessions touch --mode steer` at the start of each pass if the
mode is no longer `steer`. After any compaction or resume, verify the fleet
watcher is still armed and re-arm if not.

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

What the report gives you is a finding; what to do with each one is yours:

- **Available work** — staff it. An `!` row has waited past the staffing
  threshold; an unmarked row is simply available.
- **Steering messages awaiting a seat** — unacknowledged mail no live seat
  holds: parked reports and reports left by an ended seat. Acquiring that scope
  hands them over; acknowledged reports stay settled and are never inherited.
- **Unacked injected (this session)** — your inbox, already shown, still
  awaiting `yoke messages acknowledge MESSAGE-ID`. Not the seat-awaiting
  count above. An overflow pointer means the body never injected: read
  `yoke messages get MESSAGE-ID` and ack; the row stays pending.
- **Idle holders** — probe and revive. A holder that stamped `--mode parked`
  declared its wait, one inside a long call is listed under **In flight**, and
  one the provider stopped under **Vendor-stopped sessions**; none of the
  three appears here. A starved holder is also burning down its stale clock,
  so read `stale_eligible_at` and `effective_stale_ttl_minutes` from its `yoke
  sessions list --json` row while triaging: at `stale_eligible_at` the reclaim
  sweep releases its claims and the item reads as untouched, so a holder
  near reclaim is revived before anything else in the pass.
- **In flight** — inside a watcher or merge landing wait: quiet because the
  command holds the turn, so nothing to do. Past 45m it rejoins **Idle holders**.
- **Starved delivery** — read which shape the row is. *no delivery attempted*
  means the plane owed a wake and made none; *last attempt failed (reason)*
  names a refusal to fix, and one reason repeating across a machine's rows is
  that relay. The reason is a code; the diagnosis behind it sits on the
  recipient's machine, so pull it with the row's own `evidence` clause before
  guessing — it round-trips through that machine's relay and is read-only:

  ```text
  yoke session-control evidence get --session {SESSION_ID}
  ```

  *recipient turn in flight* is no failure: the worker is inside an
  unreturned tool call, the envelope lands on that call's own hook, and a wake
  would start a second turn — leave it. Otherwise use the wake or **Revive**
  bridge below.
- **Vendor-stopped sessions** — the model provider ended that worker's turn,
  not the worker. The end of the row says who moves next: an attempt and a
  time is the relay's, so leave it. A row naming you has no retry coming — an
  exhausted quota or rejected credentials (fix the account, not the session),
  or a spent budget, meaning every resume died the same way. Read the lane
  first: a worker that produced commits is worth resuming, one that never got
  a turn in is better reclaimed onto a fresh session; the same failure on
  every row of a machine is the provider or that client build.
- **Unregistered launches** — read which hand the row asks for. *native is
  live — bind it* means the process is up and only the binding is missing, so
  reconcile it onto the session the row names. *native is dead — reconcile,
  then retry* means the process exited; the row quotes the last line it wrote
  and its exit code, which is the reason to fix before retrying anything.
  `spawn_started` or `spawn_alive` in `native_launch_phase` belongs to the
  first process. Wait through `deadline_at`; reconcile refuses and retry
  reattaches without duplication. Otherwise use the commands below:
  `session_control.launch.list` reads `session_launches`;
  `session_control_launches` does not exist:

  ```text
  yoke session-control launch list --project {_project}
  yoke session-control launch reconcile {LAUNCH_ID} --json
  yoke session-control launch retry {LAUNCH_ID} --json
  ```
- **Abandoned launches** — the mandate reached a worker that never started:
  no claim, no message, no completed tool call, and its native is now gone.
  The item reads unclaimed rather than wrong, so nothing else in the pass will
  surface it. Read the quoted last line — a refusal that will repeat needs
  fixing before the work is restaffed — then staff the item again.
- **Landed without close-out** — merged already; only bookkeeping is owed.
  Message the named holder to re-enter `yoke merge item PREFIX-N`, which
  closes out from the recorded landing; on `no live holder`, restaff. Never
  redo the merge.
- **Dead waits** — a row naming an ended answerer, or an answerer whose own
  item is terminal, means no reply is coming: answer on the ended session's
  behalf, sending the asker the answer plus the current state of whatever
  it was waiting on. A `unresolved` row is an open question with a live
  answerer; it is context for the probe, not a finding to act on. Never
  send a bare `WAKE` to an idle holder without reading its row here — a
  wake alone parks it on the same question.

- **Plan limits** — informational table, one row per surface window (quota
  left, time-to-reset, headroom). Each row names its model scope — `weekly ·
  all models` beside `weekly · Fable`. Compare headroom across every surface
  and window; under 100% can hit a wall before its reset. Approaching walls
  go to the operator; these numbers never disable a surface or gate a launch.
- **Capacity** — unlike plan limits, the line under each machine's launch
  balance does gate launches. `AT CAP, launches refuse` means the plane
  refuses there: wait for a landing to free a lane, raise
  `max_worker_lanes` in that machine's `~/.yoke/config.json` settings, or
  place the launch elsewhere with `--machine`. `capacity unreported` is an
  older relay, not a roomy machine.

Two things the report deliberately does not do, so do them yourself:

- **Re-verify ownership immediately before launching or reclaiming.** The gap
  between the report's composition and your action is one more claim handoff
  window. Observed: a sweep hit that window and staffed a second worker onto
  a healthy item.

  ```text
  yoke claims work holder-get PREFIX-N
  ```

- **Set the hold flag on work you are holding on purpose.** The report
  excludes frozen and operator-blocked items rather than guessing intent
  from age, so an item you have parked reports as available until you say so
  with `yoke items freeze PREFIX-N` or `yoke items block PREFIX-N --reason
  TEXT`. Work that will never resume is `yoke items cancel PREFIX-N --reason
  TEXT`, not freeze.

The dashboard session card carries these signals faster when the operator has
it open: a server-active session reads `active now` under a minute and `idle
<age>` once quiet; a server-stale one keeps `stale <age>` (or `stale ·
activity just now` after fresh activity), and a claim-holding card adds a
`waiting` / `probed` / `possibly stale` pill past the staleness window. The
server's classification against the executor-aware TTL (1440 minutes on this
surface) solely decides alive versus stale, so `idle 6h` can still be a
session the control plane counts. The age says how long it has been quiet.

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

For each authenticated inbound message: acknowledge immediately, then
apply only what the report justifies.

```text
yoke messages acknowledge MESSAGE-ID
```

Typical report body: `DONE PREFIX-N <one-line summary>`. When a
DONE envelope arrives, treat it as a prompt to verify, not proof of
completion. Workers can finish without sending one, too. Confirm both the
item status and the latest matching claim's `release_reason=completed`:

```text
yoke items detail get PREFIX-N --json
yoke db read "SELECT release_reason FROM work_claims WHERE item_id = {BARE_ITEM_ID} ORDER BY id DESC LIMIT 1"
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

### 6. Deploy merged work in batches

Workers merge but never create or dispatch deployment runs. The steerer owns
batch delivery through the **prod control-plane** db-admin connection, even
when the target environment is stage. Pin one source SHA and use that same SHA
for stage and production:

```text
yoke --env <cp>-db-admin deployment-runs create {_project} {FLOW} --environment {ENV} --project-repo-path {CHECKOUT} --source-ref {PINNED_SHA}
yoke --env <cp>-db-admin watch deploy -- {RUN_ID}
```

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
dependency-edge queue, and the recipes currently in force. A successor must
be able to cold-start the scope from the claimed document alone.

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
