# /yoke steer — standing loop

Run this loop after the steering-scope claim and strategy-doc lock are held. Each
pass reads the claimed document first, then keeps it current while moving the scope.

Do not invoke `/yoke feed`.

## Wake sources

- A delivered session message (acknowledge first, then act).
- A periodic frontier check when no message is waiting.

<!-- YOKE:HARNESS claude start -->
In a Claude steering session, arm a standing `Monitor` on a fleet-delta
probe and/or a `ScheduleWakeup` fallback of at least 1200 seconds. This keeps
quiet stretches producing frontier passes without manual polling.
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
mode is no longer `steer`.

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

Positive wake events are not enough. Run this checklist **first** on every
periodic pass — before consuming events, messages, or worker reports — and
run it whether or not anything looks wrong. When a pass arrives dense with
events, the events wait and the checklist still runs; never the reverse.
Event handling expands to fill the pass, and this checklist is the only
detector for the failures that arrive as silence.

- **Outbound delivery:** find every envelope still `state='pending'` with
  `injection_count=0` past the project's grace window whose recipient has
  made no tool call since the send. Sender is not a filter: worker-to-worker
  and worker-to-steerer envelopes starve exactly like the ones this steerer
  sent, and recipient idleness is the whole trigger.

  ```text
  yoke db read "SELECT r.message_id, r.session_id, r.created_at, s.last_tool_call_at FROM session_message_recipients r JOIN harness_sessions s ON s.session_id = r.session_id WHERE r.state = 'pending' AND r.injection_count = 0 AND r.created_at::timestamptz < now() - interval '10 minutes' AND (s.last_tool_call_at IS NULL OR s.last_tool_call_at::timestamptz < r.created_at::timestamptz) ORDER BY r.created_at DESC"
  ```

  Treat every returned row as starved and revive it immediately: use the
  registered wake when available, otherwise the manual native-resume bridge
  under **Revive starved workers** below.
- **Idle claim holders:** any session holding a live work claim whose
  `last_tool_call_at` is older than **20 minutes**, whatever its liveness
  label says. Never key this check on `liveness=stale`: a claim-holding
  session carries a 1440-minute stale TTL, so a worker idle for two hours
  still reads `active` and a label-based check never fires. Observed: a
  holder sat idle 2h mid-item while the steerer watched claim-count churn
  and saw nothing.

  ```text
  yoke db read "SELECT (c.scope::json->>'item_id') AS item_id, c.session_id, s.mode, s.executor_surface, s.last_tool_call_at, round(extract(epoch FROM (now() - s.last_tool_call_at::timestamptz)) / 60) AS idle_minutes FROM work_claims c JOIN harness_sessions s ON s.session_id = c.session_id WHERE c.released_at IS NULL AND c.target_kind = 'item' AND s.ended_at IS NULL AND s.mode <> 'parked' AND (s.last_tool_call_at IS NULL OR s.last_tool_call_at::timestamptz < now() - interval '20 minutes') ORDER BY s.last_tool_call_at NULLS FIRST"
  ```

  A holder that stamped `--mode parked` declared its wait and the query
  excludes it. Every other row is probed and revived. A starved holder is
  also burning down its stale clock, so read `stale_eligible_at` and
  `effective_stale_ttl_minutes` from its `yoke sessions list --json` row
  while triaging it. At `stale_eligible_at` the reclaim sweep releases that
  session's claims and its item reads as untouched, so a starved holder
  near reclaim is revived before anything else in the pass.
- **Dead waits:** before reviving an idle holder, read what it last asked
  and who was meant to answer. A `WAKE` alone parks it on the same question.

  ```text
  yoke db read "SELECT m.created_at, r.session_id AS intended_answerer, r.state, a.ended_at AS answerer_ended_at, left(m.body, 200) AS body FROM session_messages m JOIN session_message_recipients r ON r.message_id = m.message_id LEFT JOIN harness_sessions a ON a.session_id = r.session_id WHERE m.sender_session_id = '{IDLE_SESSION_ID}' ORDER BY m.created_at DESC LIMIT 5"
  ```

  A non-null `answerer_ended_at`, or an answerer whose own item is already
  terminal, means no reply is coming. Answer on the ended session's behalf:
  send the asker the answer plus the current state of whatever it was
  waiting on. Observed: a worker asked a peer to reply if it saw a path
  overlap as order-dependent; the peer merged, went `done`, and ended, so
  the asker waited on a reply that could never arrive.
- **Unregistered launches:** any launch past `deadline_at` without a
  `registered_session_id` gets `launch reconcile` followed by `launch retry`.
- **Unowned in-flight work:** a non-terminal item with zero live claims is a
  finding only once it has been unowned **continuously past 15 minutes**.
  Never act on a snapshot: every lifecycle segment boundary releases the
  claim and reacquires moments later, and a sweep reading that window as
  abandonment launches a duplicate worker onto live work. Observed: a sweep
  hit that window and staffed a second worker onto a healthy item; the
  duplicate refused to override and reported the conflict, which is the only
  reason it cost nothing.

  ```text
  yoke db read "SELECT i.id, i.status, i.title, max(c.released_at) AS last_release_at FROM items i LEFT JOIN work_claims c ON c.target_kind = 'item' AND (c.scope::json->>'item_id')::int = i.id WHERE i.project_id = {PROJECT_ID} AND i.status NOT IN ('idea', 'done', 'cancelled', 'stopped') GROUP BY i.id, i.status, i.title HAVING count(*) FILTER (WHERE c.id IS NOT NULL AND c.released_at IS NULL) = 0 AND coalesce(max(c.released_at)::timestamptz, i.updated_at::timestamptz) < now() - interval '15 minutes' ORDER BY 4"
  ```

  Then re-verify ownership immediately before launching or reclaiming — the
  gap between the sweep and the action is one more handoff window. A holder
  returned here ends it: the item is owned, take no action.

  ```text
  yoke claims work holder-get PREFIX-N
  ```
- **Landed without close-out:** any item whose pull request is merged while
  the item remains non-terminal gets an immediate nudge to its live claim
  holder; with no live holder, route the normal starvation/restaffing path.

The dashboard session card carries these signals faster when the operator
has it open: every card renders an explicit `idle <age>` line, and a
claim-holding card carries a `waiting` / `probed` / `possibly stale` health
pill. Read the idle age, not the pill — the pill only appears past the
staleness window, the same 1440-minute clock that makes the liveness label
useless here. The queries above are the headless pass.

Wake sources are events; failures are silences — every pass scans the
silences.

### 2. Consume worker reports

Item-addressed messaging is the default. The server resolves the live
holder of a claim; do not hand-copy or expand a session UUID.

```text
printf '%s' "$BODY" | yoke say --item PREFIX-N --stdin
```

Also `--epic-task ITEM:N` and `--process KEY`. `--session UUID` is the
fallback for a claim-less recipient only (this itemless steerer is one).
Never expand a truncated session id by hand.

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

For an idle Cursor or Codex recipient, check for a message stuck past the
project's grace window with `state='pending'` and `injection_count=0`:

```text
yoke db read "SELECT session_id,state,injection_count,created_at,wake_after FROM session_message_recipients WHERE session_id = '{SESSION_ID}' AND state = 'pending' AND injection_count = 0 ORDER BY created_at DESC"
```

Until automatic wake escalation replaces the manual bridge, resume a stuck
Cursor session directly:

```text
cursor-agent --resume <session-id> --print --output-format json --workspace <dir> --trust '<instruction>'
```

A run of workers that die or hang within a few tool calls on one otherwise
installed and signed-in surface may mean vendor quota or credits are
exhausted, which currently resembles a crash. Verify by running that harness
CLI interactively, rebalance new lanes onto the other surfaces while it
recovers, and restore the steady-state balance afterward.

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

Steer existing work in its pinned workflow; never convert or re-file it.
For ordinary new work filed by the steerer, default to
`/yoke idea --workflow dash` unless the work genuinely needs Issue, Epic, or
Blitz structure, or the operator directs another workflow.

When a chunk of the doc needs an implementer:

1. File a Blitz from the doc (`/yoke idea --workflow blitz "{title}"`).
   Link it before anyone claims it:

   ```text
   yoke strategy execution link ITEM --slug {SLUG} --project {_project}
   ```

2. **Release the document lock** so the worker can claim the Blitz. A
   session-held lock and a live Blitz on the same slug are mutually exclusive
   — leaving the lock held is a handoff defect.

   ```text
   yoke strategy doc-claim release {SLUG} --project {_project} --reason "blitz-handoff"
   ```

3. Encode `item_dependencies` edges (or an explicit no-edges attestation
   on the filed items) in the same action that files a related batch.
   Title-only batches that are already claimable are a defect.

4. Launch per [`worker-lifecycle.md`](worker-lifecycle.md). After the
   Blitz reaches `done`, re-acquire the document lock if this coordinator
   is still steering the slug.

### 5. Staff unpicked runnable work

When runnable work sits unclaimed, invoke the steering backstop — not a
hand-rolled spawn, and not `/yoke do`:

```text
yoke steering backstop evaluate --project {_project}
```

The backstop launches only work the scheduler already calls runnable that
carries no live work claim and has waited past the project's unpicked
grace. It refuses callers who do not hold the steering-scope claim. Use
`--dry-run` only to inspect; a live pass files the launches.

Prompt launches for newly runnable unclaimed items follow
[`worker-lifecycle.md`](worker-lifecycle.md) (keep the frontier maxed
out). The backstop is the safety net for work that sat.

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

Escalate to the operator when the loop cannot choose: conflicting
reports, a scope that needs a new project, a lock it cannot release
without destroying in-flight work, or any decision the operator reserved.
Present the decision, the evidence, and the recommended option, then
**wait**. Do not guess. Do not implement. Do not file a substitute item
to dodge the gate.

Everything else continues autonomously.

## Stop

A clean stop is wrapup in `SKILL.md` step 5: release the document lock
and the steering-scope claim. An abandoned coordinator is reclaimed by
the stale sweep; do not treat that as a successful wrapup.
