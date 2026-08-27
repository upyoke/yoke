# /yoke steer — standing loop

Run this loop after the steering-scope claim and the strategy-doc lock are
held. No new scheduler: each pass is a message-wake or a periodic frontier
check. Keep the claimed document current on every material change.

Do not invoke `/yoke feed`.

## Wake sources

- A delivered session message (acknowledge first, then act).
- A periodic frontier check when no message is waiting.

<!-- YOKE:HARNESS claude start -->
In a Claude steering session, arm a standing `Monitor` on a fleet-delta
probe and/or a `ScheduleWakeup` fallback of at least 1200 seconds. This keeps
quiet stretches producing frontier passes without manual polling.
<!-- YOKE:HARNESS end -->

Codex and Cursor steering sessions rely on message wakes plus their native
loop. Never teach them Claude-only wake primitives.

Stamp `yoke sessions touch --mode steer` at the start of each pass if the
mode is no longer `steer`.

## Pass

### 1. Read the scope frontier

```text
yoke charge schedule --project {_project} --json
yoke claims steering list --project {_project} --active-only --json
```

`charge.schedule` is a frontier **read**. It does not dispatch and it is
not feed. Record runnable unclaimed items, dependency gates, and anything
already claimed. Write material frontier movement into the doc (step 7).

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
- **Stale claim holders:** any session with a live work claim and
  `liveness=stale` gets the same probe-and-revive treatment. A starved
  holder is also burning down its stale clock, so read `stale_eligible_at`
  and `effective_stale_ttl_minutes` from its `yoke sessions list --json`
  row while triaging it. At `stale_eligible_at` the reclaim sweep releases
  that session's claims and its item reads as untouched, so a starved
  holder near reclaim is revived before anything else in the pass.
- **Unregistered launches:** any launch past `deadline_at` without a
  `registered_session_id` gets `launch reconcile` followed by `launch retry`.
- **Silent in-flight work:** any in-flight item with no worker activity beyond
  the project's sanity window gets an immediate holder probe and revival.
- **Landed without close-out:** any item whose pull request is merged while
  the item remains non-terminal gets an immediate nudge to its live claim
  holder; with no live holder, route the normal starvation/restaffing path.

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

### 3. Work the strategy document itemless

```text
yoke strategy doc get {SLUG} --project {_project}
```

The coordinator holds no work item. Plan-level progress lives in the
claimed doc: objective, frontier, decisions, gates, dead ends. Edit
through the registered strategy surfaces (`strategy.doc.get`,
`strategy render`, `strategy ingest` / `strategy.doc.replace`). The doc
plus the items survive coordinator death.

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
