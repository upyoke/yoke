# Shared coordination model

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Sessions](../index.md) > Shared coordination model
<!-- /yoke:breadcrumbs -->

Shared-operation leases coordinate test hosts and governed data work; session views show claims, registered identity and measured usage.

## Shared-operation coordination claims

Three `work_claims` target kinds coordinate a resource that is not a unit
of backlog work. They live in the same table as every other claim, so one
system carries session binding, heartbeat, telemetry, and the board's
Claims column for every hold.

| target_kind | scope | Coordinates |
|---|---|---|
| `migration_serialization` | `{"project_id":N,"model":M,"item_id":N}` | Migration territory for one model, owned by the authoring item |
| `qa_admission` | `{"test_machine":NAME}` | One physical test machine, globally |
| `route_qualification` | `{"project_id":N,"grant_key":K}` | One private-route qualification grant |

Each has a unique partial index over its exclusivity unit, so a second
holder is refused at the database rather than by a read-then-write race.
`migration_serialization` conflicts on `(project_id, model)` — the
`item_id` in scope records who owns the hold, not what is held, which is
what lets the same item re-enter and heartbeat while any other lane is
refused. `qa_admission` has no project in scope on
purpose: a physical machine is one resource whichever project drives the
run.

**Stickiness is the property that separates these kinds from the rest.**
`migration_serialization` and `qa_admission` are sticky: the
stale-session sweep, the session-end release, and the claim-free end
check all skip them, because the migration and the remote suite keep
running after the session that started them goes quiet. Recovery is the audited steering-seat operator release,
never an automatic reclaim. `route_qualification` is liveness-bound like
the backlog kinds — a grant is only valid while its steering session
lives — so the sweep reclaims it normally.

Each claim is addressed by one operator key: `LIVE_DB_MIGRATION:<model>`,
`QA_HOST:<machine>`, and the qualification grant token. QA_HOST keys are machine-scoped: list with `yoke coordination-claim list --key QA_HOST:<machine> --active-only --json`, ignoring any project filter. A session holding a live steering seat on the holder's project recovers a reviewed row with `yoke coordination-claim release --key QA_HOST:<machine> --claim-id N --holder-session-id S --reason R`; permission remains the holder's project `claims.release`. Other key kinds still require `--project P` for operator release. QA host holders can release by claim id with `yoke claims work release --claim-id N --reason TEXT` after run completion; requirement reads and artifact uploads retain the stored member's project authority after membership ends.

**Test Machine queue (`qa_test_machine_waits`).** Every walk that needs a Test Machine waits at one place across its host lines, set when it first queues. Each row names one machine that can serve its waiter: `test_machine`, `session_id`, `actor_id`, `queued_at`, optional `qa_plan_execution_id`, `state` (`waiting`, `reserved`, `granted`, `cancelled`), `claim_id` of the reserved turn, the `resume_command` that takes it, `rationale`, `settled_at`, and `need_id`. A walk run with `--test-machine`, resuming on the machine that holds its state, or a manual claim has one row; every other walk has one row per verified machine whose OS and capability tags match, all sharing `need_id`, and a case with OS slots has one such need per slot. When a machine frees, it goes to the oldest eligible waiter with a row on it; once one row of a need is reserved its sibling rows stop competing, consuming the reservation cancels them, and a released reservation that ends the wait cancels them too. The waiter takes a machine reserved for it before any other. One advisory lock serializes every reservation across the queue. A scoped plan execution joins when its case cannot lease the host or the host is unhealthy (the newer of its verification and its last successful golden capture is a failed verification; a plan case whose SSH connection fails records that failed verification as `ssh_unavailable` and joins instead of recording an error verdict); a refused `yoke claims coordination-claim acquire` joins with the same command as its resume. A session keeps its first `queued_at` while it waits unless steering moves it. A shared deployment-stage execution that has not held the host, joining after the latest earlier execution of its run, stage and shared plan was aborted while holding it, takes that execution's place: the earliest `queued_at` of its granted waits or `claimed_at` of its leases on the host. Every release of a healthy host — holder, `claims work release`, operator, or cancellation — reserves it for the oldest waiter it can serve whose session has not ended, and wakes that session; its next acquire consumes the reservation. A `yoke test-machine reset` or `verify` its holder runs on a reservation kept for one of its plan executions borrows that turn instead: the claim keeps its `qa-host-turn:` reason and the wait stays `reserved` through submit or abort, so the plan's own `yoke qa plan run` still consumes it. Two releases first keep a same-session **hold-over** instead (`qa_host_holdover`): a direct operation's lease (`yoke test-machine exec`, desktop access, browser sign-in) released with no waiter for that machine, or with waiters queued behind the hold-over that lease consumed, keeping that first hold-over's start so polling cannot starve the queue; and every host an execution held or had reserved when its own live session stops it (`yoke qa plan abort`), whatever the queue holds. A hold-over is a `reserved` wait with no execution beside the claim, reason `qa-host-turn:holdover`; the session's next acquire consumes it, another session's acquire is refused and queues behind it, and it lapses 120 seconds after it starts (session heartbeats never extend it). An acquire on the host or control-plane upkeep releases a lapsed one, which serves the queue. `yoke test-machine exec` names the hold-over and its expiry on stderr, `test_machine.get` reports it as `active_lease.holdover_expires_at`, and the owner's stop receipt lists it as `test_machine_holdovers`. An unhealthy host is not reserved; the release that ends a successful `yoke test-machine verify` or `golden-capture` on it serves the queue. Session end, execution settlement, and a release of an unconsumed reservation cancel the wait, except a reservation held for a plan execution whose owning run has not opened its QA stage. Such an execution (a takeover moved it to a successor still before item QA) keeps its place in the queue but is passed over when a host is served, and a release of its reservation returns the wait to `waiting` at its place instead of aborting it `qa_host_turn_released` (`qa_host_stage_unopened`). When the stage opens, the stage-wait notice sends its owner to `yoke qa plan run`, which re-freezes the same execution and serves it at its original place. A held `QA_HOST` lease (not an unconsumed reservation or hold-over) whose session is parked, process-exited or ended with no tool call, subagent tool call (`last_child_tool_call_at`), recorded host operation on the lease or heartbeat from the live execution holding it for the machine setting `qa_host_idle_hold_minutes` (default 60) is returned by control-plane upkeep (`qa_host_idle_hold`): first every reservation of a host set still waiting on that host goes back to `waiting` at its execution's own place and is released to the queue, then the lease is released through the manual release path, which records the reset owed and aborts the walk with `qa_host_idle_hold_expired` and the `yoke qa plan run` that starts it again. A recent subagent tool call or a recent custody-checked heartbeat from the live QA execution, newer than the holder's own last tool call, keeps its driver and companion leases in use; a heartbeat the holder's own walk left before it parked or exited does not. Each release serves the queue and wakes the next waiter it can serve. Claim heartbeats and watcher pulses never extend the hold. A plan execution waiting for a host set whose session is parked, process-exited or ended with no tool call for that same limit keeps its place in the queue but is passed over when a host is served while it still waits on another host; upkeep hands each partial reservation it already holds to the next waiter (`qa_host_idle_waiters`). A running turn newer than the last recorded exit marks a holder or waiter as present before its first tool call completes. When the waiter returns, the next release serves it at its place.

A set reserves hosts only at the front of every required line. If it falls
behind, it returns its partial reservations and keeps its place. Notices show
positions by host, counting the reserved turn first. Steering commands:

```text
yoke test-machine queue place --execution ID --host H --position N --reason TEXT
yoke test-machine queue hand-over --from ID --to ID --host H --reason TEXT
```

`place` moves the execution before N on H, or last if N exceeds the line. Its
place applies to all its hosts and survives resume. `hand-over` gives the turn
to a waiter first on its other hosts and keeps the former holder queued.
Active use, including reset and verify, prevents handover. A covering steering
seat can place, hand over, or [withdraw a wait](../../functions/qa.md#withdraw-a-test-machine-wait).

Deployment runs take no coordination claim. `deploy_serialization` is the
retired per-project deploy lock: nothing takes one, a `DEPLOY:` key refuses
with `deploy_lock_retired`, a hold from before the retirement is released by
its claim id, and runs serialize by the servers they occupy, described in
[run membership and target occupancy](../../deployments/model/run-members.md).

### BOARD.md Claims column rendering

`.yoke/BOARD.md` is a generated, untracked view. Nothing rebuilds it
automatically; run `yoke board rebuild`. Board settings live in the project's
`project-policy` capability; change them with
`yoke projects capability-settings set` (read its `--help`).

The Active Harness Sessions and Recent Sessions tables share one Claims column that renders all three primitives as keycap entries. The shapes:

| Primitive               | Active shape                | Example                            |
|---                      |---                          |---                                 |
| work_claim (item)       | `PREFIX-N`                     | `PREFIX-N`                         |
| work_claim (epic task)  | `PREFIX-N T###`                | `PREFIX-N T008`                    |
| work_claim (process)    | `⚙ <process_key>`           | `⚙ FEED`                           |
| work_claim (steering)   | `🛞 steering <project> · <documents>` | `🛞 steering yoke · CURRENT-PLAN` (a project seat holds no document and renders `🛞 steering yoke`) |
| work_claim (other kind) | `<kind>:<compact-scope>`    | `future_kind:{"k":"v"}`            |
| uncovered strategy_doc_claim | `🛞 <project> · <document>` | `🛞 yoke · MISSION`              |
| work_claim + same-item path_claim decoration | `PREFIX-N 📁<total>`           | `PREFIX-N 📁23`                    |
| path_claim orphan       | `📁<total> (PREFIX-N)`         | `📁5 (PREFIX-N)`                   |
| path_claim process anchor | `📁<total> (⚙ process_key)` | `📁3 (⚙ FEED)`                     |
| coordination claim      | `🔒 <key>`                  | `🔒 QA_HOST:mac-mini-lab` |
| coordination claim (item-owned) | `🔒 <key> (PREFIX-N)` | `🔒 LIVE_DB_MIGRATION:primary (PREFIX-N)` |

Rules: same-session multiple `path_claims` on the same item roll up into one keycap with the summed declared-path total; coordination claims never decorate work_claims (they stay `🔒` keycaps and are omitted from the work-claim list so they do not also render as `?`); ordering inside a row is work_claims → uncovered document locks → orphan path_claim keycaps → coordination claims. A steering seat folds in document locks from the same project: current seats name current locks, while released seats name released locks whose hold windows overlapped. Project id is part of the lock key, so same-named documents in two projects remain separate rows; a lock with no matching seat keeps its own keycap. A seat without a lock renders `no doc lock`. During a server/client rollout, an older recorded board payload without the pairing read keeps the seat and lock as separate rows instead of failing the render. Repeat work claims on the same rendered target and repeat coordination claims on the same key each collapse to the most recent row (one keycap). Steering occupancy is this column, not a separate Steering section. Release reasons are not rendered on Claims — drill into claim detail surfaces for audit history. Released path_claims and coordination claims do not appear on active-session rows. Per-file enumeration is intentionally out of scope — operators drill into per-file detail via `path-claims list --item PREFIX-N`.

### Scheduling and registered identity
`compute_schedule()` serves charge, steering, board, fleet and frontier. Explicit staffing follows pinned workflow bindings. Registration separates requested facts from provider-attested served model/effort/window facts; missing served values remain unattested.
Window sources are declared by `yoke_contracts.session_context_window_sources`: Codex rollout `turn_context.model_context_window`; Claude status-line JSON `context_window.context_window_size`; Cursor none. Cursor's store names only `modelName`, display labels spell a window, and `cli-config.json` context is a request. Claude's rendered `statusLine` records the window for the next hook and displays model/window/usage; Claude permits one status line and hides most footer keyboard hints when configured. An override in `.claude/settings.local.json` replaces it and gives up this attestation, leaving the window NULL. Claude alone records its window separately from its model, so its cheap window read continues after expensive model reads settle. Settlement requires a served-model hook COMPLETED against the control plane: failed-open/timed-out relays retry. NULL model means unattested or not landed.
`usage_totals` records measured consumption from `yoke_contracts.session_usage_sources`: Claude assistant `message.usage` (cache writes split by lifetime, thinking within output), Codex cumulative `token_count` (input includes cached input, output includes reasoning), Cursor optional turn `stop` fields or print-mode result `usage`; absent fields mean unavailable for that surface. Totals include every child agent (subagent) on every harness, discovered by `yoke_harness.child_agent_artifacts`: Claude `<transcript stem>/subagents/agent-*.jsonl` (own offset per file, one message-id dedup set across files), Codex child-thread rollouts named by `SubAgentActivity` items (each thread's own cumulative total, summed), Cursor child-turn payloads flagged `is_subagent_session` (deduplicated by `generation_id`). Context compaction and summarization calls that write no usage row are a known undercount, never estimated; `session_usage_sources.UNRECORDED_USAGE_UNDERCOUNT` names it in every usage note. Readers normalize disjoint billable buckets `input`, `cached_input`, `cache_write`, `cache_write_long`, `output`. `reasoning` is a labelled subset of output, never added again. `cost_caveat` describes pricing uncertainty (multiple models in one thread or unreadable model history), separately from measured token completeness. Parse stored documents through `yoke_contracts.session_usage_facts.usage_from_document`.
Readers are incremental, bounded and idempotent. A per-session watermark under machine Yoke home folds only new artifact bytes; relay sends absolute totals and the control plane replaces them, so duplicate delivery cannot inflate usage. Fixed-size streaming retains accumulators, not whole artifacts. Oversized records are streamed for declared relevant scalars; finish a record crossing the scan-byte bound before stopping so the next offset never skips its statement. An unreadable relevant statement marks `partial` with reason; irrelevant large records cost no completeness; stopping short merely says resume. Reader versions trigger one re-fold when recovery improves: accumulating readers restart from zero/empty totals, replacement readers use held totals. Codex's resumable fold also carries model/effort/window; Claude's model read uses a bounded transcript tail.

Only the newest served statement may attest a fact. A fold behind the artifact end attests nothing historical and reopens hook resolution until caught up; settling otherwise stops model scans. Persist checkpoints atomically and serialize folds per session/reader, avoiding offset-zero replay or an older offset overwriting a newer one. Mid-fold hooks use persisted totals. Claude deduplicates repeated response usage by message id. Rotation/truncation rereads from start and marks partial with earlier history gone. A reading measuring nothing never replaces a measured one; no token source means unavailable with reason, never fabricated zero.

Cursor print-mode result arrives after the last hook. The starting machine folds its native's settled capture, never a half-written JSON object, deduplicates `request_id`, and relays through `session_control.relay.liveness` with the same never-unlearn rule even if an active claim keeps the session alive. Attribution follows machine custody of the launched native, not identity printed in the result.

The same row also records what the session **consumed**, in `usage_totals`. Consumption is read from the same harness artifact and relayed by the same hook path as the served model, but no two harnesses state it in the same shape: Claude stamps a `message.usage` block on every assistant transcript row, splitting cache writes by cache lifetime and folding thinking into its output count; Codex writes one cumulative `token_count` rollout event whose input total already contains its cached input and whose output total already contains its reasoning; Cursor folds optional turn `stop` token fields, child-agent turns included, and print-mode result `usage` when present, otherwise `unavailable` for that surface. Every reader adds the session's child agents into the same per-model totals. Each reader converts its source into the same disjoint billable buckets before anything is stored — `input`, `cached_input`, `cache_write`, `cache_write_long`, `output`, with `reasoning` kept as a labelled subset of output that is never added to a total — so one calculation prices every harness and no subset field is charged twice. That per-harness map is data rather than prose: `yoke_contracts.session_usage_sources` carries it, including Cursor's turn source and the standing undercount of calls no harness writes a usage row for. One field of a stored document is deliberately not about counts: `cost_caveat` names why an estimate priced from those tokens is less certain than the tokens themselves — a thread-wide total that more than one model served, or a model history holding a record that could not be read — so tokens a source stated exactly are never marked partial for a reason only pricing cares about. Read a stored document with `yoke_contracts.session_usage_facts.usage_from_document`, never as raw JSON. Its observation is an aware instant internally and fixed-six UTC/null in mutable stored JSON; carried readings canonicalize that field without dropping unrelated facts.
Dollar cost is derived, never stored: `yoke_contracts.session_usage_pricing` uses the immutable catalog revision effective at initial `offered_at`, including after reactivation. Unknown model/unpriced bucket yields named partial/unavailable cost; an estimated rate remains labelled estimated. Price gaps never block raw capture. Every displayed number is an **API-equivalent estimate**; subscription meters have no published dollar conversion. Roster clients use derived `usage_tokens`, `usage_status`, `usage_cost_usd`, `usage_cost_status`, `usage_note`.

**Machine-card 24-hour usage window.** `sessions.list` with `usage_last_24h: true` is mutually exclusive with every other filter and returns unpaginated authorized rows (`actor_visible_project_ids`, plus readable sessions outside any project unless a project is named) with session/machine ids and derived usage fields. Cohort: sessions ended in trailing 24 hours UNION sessions started (`offered_at`) inside it and still open. These disjoint halves count each session once; older still-open sessions are excluded because cumulative totals do not measure only this window. `sessions_history_read.read_recent_session_usage_by_machine` dates ended sessions through `ended_at_sql` (fallback `terminated_at`), excludes probes through shared `not_probe_session_sql`, and excludes missing `machine_id`. `appendMachineUsage` in `universe_machines_usage.js` sums per machine; labels `24H TOKENS`, `24H API COST`, `24H SESSIONS` carry the window. Fetch once per machines-panel load/redraw, independently of roster filters.

## Stranded migration lease recovery

- **Steering-seat operator release.** From a session holding a live steering seat on the project, `yoke coordination-claim release --project P --key LIVE_DB_MIGRATION:<model_name> --claim-id N --holder-session-id S --reason "..."` emits a WARN `OperatorLeaseRelease` event before the release mutation lands. It refuses to run from a hook context and records the operator reason permanently on the claim row. Sticky claim kinds have no automatic reclaim, so this is the only release before the item's landing or terminal status.

## Related

- [Session model](sessions.md)
- [Run membership and target occupancy](../../deployments/model/run-members.md)
- [Timestamp discipline](../../databases/migrations.md#timestamp-discipline)
