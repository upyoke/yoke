# Hooks Reference

Harness-native startup, guardrails, telemetry and session end run through Python
owners. Load this contributor reference when changing or diagnosing hooks.

## Canonical owners

| Surface | Owner |
|---|---|
| SessionStart hook (session registration, emits `HarnessSessionStarted`) | `yoke hook evaluate SessionStart` |
| UserPromptSubmit hook (startup orientation and its re-delivery, emits `HarnessSessionSentFirstUserPromptSubmit`; idempotent re-registration safety net) | `yoke hook evaluate UserPromptSubmit` |
| Session end (guarded end-if-empty; live claims or a resumable chain keep the session active) | `yoke hook evaluate SessionEnd` |
| Pre-tool guardrail deniers (Bash / DB-command lint, policy deny) — each emits `HarnessToolCallDenied` via the shared `emit_denial_event` helper before returning its deny JSON. Every rendered denial names the same registered check id the audit row records. | `yoke_core.domain.lint_db_cmd` (DB-command branches retain `lint-sqlite-cmd`; nested-Claude branches use `lint-nested-claude-cli` — classified on the caller's harness family by `yoke_core.domain.lint_nested_claude_cli` and keyed to its own `lint_db_cmd_nested_claude_cli` setting — or `lint-remote-claude-cli`), `yoke_core.domain.lint_event_registry`, `yoke_core.domain.lint_main_commit`, `yoke_core.domain.lint_tc_label`, `yoke_core.domain.lint_write_path` |
| Pre-tool observer (emits `HarnessToolCallStarted`, whose captured instant is the start endpoint PostToolUse measures `duration_ms` from) | `yoke_core.domain.observe_pre` |
| Post-tool telemetry (emits `HarnessToolCallCompleted` / `HarnessToolCallFailed` / `HarnessToolCallStructuredExit` / `HarnessLifecycleMutationDetected`, runs anomaly detection, measures `duration_ms` between the two captured endpoints) | `yoke_core.domain.observe` for `PostToolUse` |
| DB error annotation | `yoke_core.domain.db_error_hook` |
| Subagent stop (item-worktree auto-commit safety net, `HarnessSessionStopped`) | `yoke_core.domain.agent_stop` |
| Emergency status repair | `yoke_core.engines.repair_status` |

The `yoke hook evaluate` CLI is the stable boundary project hook configs call; the spelling is identical on every transport. Other Python modules above are internal policy/telemetry owners executed behind the runner, not copy-paste hook config commands.

`Stop` and `SessionEnd` call `end_session_if_empty`: they preserve an active
session when it still owns unreleased work claims, a session-owned strategy
document lock, a keep-alive hold, an in-flight wake delivery, or a resumable
chain checkpoint. They do not drain claims. The keep-alive hold is how a
session that legitimately holds nothing — one whose whole job is to be a live
wake target — survives this path: `yoke sessions keepalive hold <session-id>
--reason ...` leases it against idle reaping, and the lease expires on its own
rather than pinning the session forever. `SubagentStop` has a different local
responsibility: it can safety-net auto-commit uncommitted work in a `YOK-N`
item worktree and then emits `HarnessSessionStopped`; it does not terminate
the parent session or release its claims.

## Transport and resident

Project hook configs call `yoke hook evaluate <event>`. Each non-dry invocation
sends event/payload, pid/ppid, cwd, environment and installed revision over a Unix
socket to one evaluator per machine user. The resident imports the engine once,
reuses an HTTPS pool and isolates each concurrent caller's context. Dry runs stay
local. The active machine connection selects in-process or HTTPS evaluation.

On HTTPS, the client reads the payload and detects executor/agent identity once.
It evaluates `LOCAL_STATE_POLICIES` through
`yoke_harness.hooks.local_subset.evaluate_local_subset`, then sends the remaining
chain to `POST /v1/hooks/evaluate` with machine credentials, hook schema, event,
stdin, executor, agent type, entrypoint, model, execution level and remaining
deadline. Identity fields are client-owned: the server cannot inspect local
transcripts, caches or launch inputs.

Any deny wins. A client deny returns immediately without posting; a server deny
relays verbatim and discards client advisories. Two allows join sibling advisory
envelopes through `decision_render.merge_allow_stdout`. Local-state delegation
is recorded in the server's `degraded` list; it means delegated, not disabled.
The same chain machinery preserves each policy's fail-open/fail-closed behavior.

`yoke_core.hooks.remote_policy.LOCAL_STATE_POLICIES` classifies policies requiring
local Git, workspace, file or script-directory state. Payload/DB policies,
including command-shape, path-claim/session-cwd, heartbeat and telemetry, remain
server-side. Narrow `payload_extra` supplies staged Git facts to main-commit and
the effective scratch root to session-cwd; watcher captures must nest under the
calling session. Client agent type (`YOKE_HOOK_AGENT_TYPE`) and identity fields
merge into both payloads. The server binds verified bearer actors to registered
session rows (`actor_id` matches local machine-actor resolution).

The client starts the resident on demand. It retires after ten idle minutes;
a request for a different installed revision closes acceptance and re-execs,
with both revisions named in the handshake. In-flight non-daemon handlers join
before close. Neither retirement nor upgrade waits indefinitely for telemetry:
shutdown drains retained observations once for two seconds, warns on timeout,
and continues.

Socket/protocol/startup/crash failures use the canonical in-process evaluator
for that invocation. A named stderr warning is rate-limited across processes to
once per five minutes in the existing evaluator state directory. An unwritable
warning marker stays quiet without skipping evaluation. `HookDispatchTelemetry`
names `evaluator=inprocess` and the fallback reason. A missing resident never
manufactures an allow. Inspect with:

```text
yoke watch doctor -- --only hook-resident
```

The check runs on client machines for local/HTTPS, reports down as WARN with log
and startup recovery, and is N/A on server/hosted runtimes. An idle retirement is
normal; the next hook retries startup.

### Deadlines and degradation

`RESIDENT_CONNECT_GRACE_SECONDS` (2s) is one absolute budget for connect, startup
and restart handshakes, enforced on every socket operation. Once sending begins,
response wait uses `YOKE_HOOK_TOTAL_TIMEOUT_MS` plus two seconds for resident
settlement, measured from client process start; retries never extend the budget.

The shared `hook_runner_total_timeout_ms` ceiling (default 10000ms;
`yoke_core.domain.hook_runner_deadline`) spans both chain halves. Client policies
consume it in order; POST uses the remainder and passes `deadline_ms`; the server
clamps that remainder to its ceiling and stops launching policies at exhaustion.
A computed deny survives expiry. Otherwise `degraded` includes
`deadline_exhausted` and `deadline_skipped:N:a,b,c`. Server metrics are
`yoke.hook.wait_ms` and `yoke.hook.requests`, with
`outcome=completed|timeout|denied` also in the response.

Timeout, unreachable host, non-200 or invalid response degrades only the server
half to empty stdout/exit 0 plus one stderr diagnostic. Already-computed client
allow context survives; a client deny never enters that path. Claude's output
writer sends exit-2 denial reasons and guard/environment notices to stderr,
reducing a local deny envelope to reason text. Codex/Cursor retain stdout verdict
envelopes; allow context uses stdout.

### Lifecycle deduplication and orientation

`yoke_core.hooks.dispatch_dedup` collapses lifecycle repeats with the same
session/event and byte-identical payload inside `DISPATCH_DEDUP_WINDOW_SECONDS`,
recording `HookDispatchDeduplicated`. Machine-local markers are scoped by run
half so client/server cannot consume each other's markers. `PreToolUse`,
`PostToolUse`, `PostToolUseFailure` and `PermissionRequest` always evaluate
individually with their tool-use identities.

`session_orientation_delivery` records composition attempts separately from
actual allow-response delivery. A deny or killed process leaves orientation
undelivered, so the next context-bearing event repairs it once. Claude/Codex
use their per-prompt channel; Cursor's block/allow prompt channel uses its
tool-result event selected by `session_orientation_redelivery_event` and the
manifest's `inject_events`. Repair labels context and emits
`YOKE_ORIENTATION_REDELIVERED` on stderr. Preserved allow stdout during server
degradation counts as delivery. See [native discovery](public/reference/harness-discovery.md).

### Read-only observation batches

An HTTPS server advertising `read_only_observation_batch_v1` permits resident
local evaluation of tool events whose complete canonical chain contains no
decision-making guard. Classification follows chain ordering, not an allowlist;
Bash/Write/Edit guards remain synchronous. The session's first read-only event
and another at least every two seconds still relay for message injection. Other
events return locally and queue unchanged started/completed/dispatch telemetry.
The queue flushes in order every two seconds or 32 observations; heartbeat and
tool-activity state advance on commit with that bounded lag. Older servers keep
the synchronous path until they advertise support.

A 4xx other than 408/429 drops the rejected batch and emits
`YOKE_HOOK_TELEMETRY_BATCH_REJECTED` with HTTP status, rejection code and recovery.
Transient failures retry with geometric backoff to a 30-second ceiling for a
bounded attempt count, then drop. Queue length is capped. While retained,
`YOKE_HOOK_TELEMETRY_FLUSH_FAILED` reports depth and oldest age; discarded work
emits `YOKE_HOOK_TELEMETRY_DROPPED`. Disposable observations never block sessions
or pin residents/revisions; operational state has durable owners.

Evaluate and batch share `yoke_core.hooks.relayed_session_identity`. Unstamped
payloads receive conversation-alias shape checks. The client folds unmapped raw
conversation identities to empty and sets no stamp; a valid machine-local Cursor
mapping can legitimately use the conversation id as canonical session id.
Batch authorization additionally refuses a stamped session row belonging to
another actor with `HOOK_OBSERVATION_SESSION_DENIED`. A stamped id with no row
yet is accepted so its observation can register it. This actor check is
batch-only; do not add it to evaluate and block live tools during registration.

## Timing and diagnostics

The client captures interpreter process start and final stdout time. It sends
completion over the existing resident socket, adding `client_wall_ms` to matching
`HookDispatchTelemetry` without another network request on the decision path.
The configured in-process path records or relays the same field. An unconfigured
thin client leaves disposable telemetry unrecorded and never imports the engine
solely to report it.

Fallback writes `YOKE_HOOK_PHASE_TIMING` to stderr with `resident_wait_ms`,
`fallback_ms`, `client_wall_ms` and `fallback_reason`; unmeasured phases say
`not-measured`, never zero. Set `YOKE_HOOK_PHASE_TIMING=1` for healthy calls too.
The line contains durations and a refusal code, never payload/environment/secret;
rendering cannot delay or fail the tool. Resident wait includes connect/restart/
response; fallback includes its synchronous completion telemetry.

```text
yoke sessions hook-overhead [--hours N] [--json]
yoke hook benchmark --samples 5 [--json]
yoke hook benchmark --samples 5 --compare REPORT.json
```

Hook overhead reports Pre/Post client p50/p90/mean, evaluator p50, remainder and
timed/total coverage. Evaluator includes hosted server or local/admin in-process
work. Tool mean/p95 and coverage use repaired owner timestamps, globally and per
harness. `ACTIVE*` counts distinct telemetry-emitting sessions in a fixed hour;
it is neither a live roster nor simultaneous execution. `--hours` sets the
observation cutoff.

The benchmark runs harmless `true` between normal guarded Pre/Post evaluations.
It records harness/surface, available revisions, exact window/count/coverage,
durable phase context, command and envelope times. Save JSON for comparison.
Different harnesses/surfaces/revisions/commands/counts, pending delivery or missing
coverage are incomparable. A phase missing after a limit-filled query is
incomplete; client-wall completion still in flight is pending, not inferred
from stderr. Live roster and running-session bucket proxy are separate evidence.
See [performance diagnostics](public/reference/performance-diagnostics.md).

### Captured endpoints and unknowns

Tool `duration_ms` is captured end minus captured start, scoped by
`(session_id, tool_use_id)`, never ingest time. Batch delivery records its separate
`ingest_lag_ms` and `ingest_lag_status` in `context.detail`; replay retains the
same duration.

A completion arriving first inserts one closed call with its end in both
endpoints. `session_tool_call_start_reconcile` later updates only `started_at`,
keeping the earlier valid start; outcome, completion/activity count remain and
finished work never reopens. Duplicate/replayed starts change nothing.
`observe_timing` owns vocabulary/classification; `observe_db_reads` resolves start.

Every completion carries `timing_status`; only `measured` has a real duration,
including measured zero. Other statuses have null duration:

| Status | Meaning |
|---|---|
| `unknown_no_call_identity` | Missing session/tool-use id; native Cursor shell hooks omit correlation/duration (`yoke_contracts.cursor_shell_timing`). Count as unsupported coverage, omit latency statistics. |
| `unknown_no_recorded_start` | Missing start or completion placeholder after the 15-minute delivery window. |
| `pending_start_delivery` | Missing opening observation while completion is inside that window; pending, not incomplete. |
| `unknown_no_captured_end` | No captured completion instant. |
| `unknown_lookup_failed` | Lookup failed; telemetry never blocks the tool. |
| `invalid_endpoint_format` | Timestamp unreadable. |
| `invalid_negative_elapsed` | End before start: writer clock skew. |
| `invalid_implausible_elapsed` | More than a day indicates unrelated endpoints; genuinely long calls are measured, not capped. |

Reports exclude unknown durations from statistics while retaining coverage
counts. Starts or client wall inside the delivery window remain pending.

## Configuration and trust

- Claude: `runtime/harness/claude/settings.json` materializes as a regular
  `.claude/settings.json`. Hook ordering is preserved. Claude owner markers
  make those entries no-op when Cursor scans them; `.cursor/hooks.json` is
  Cursor's sole Yoke hook owner.
- Codex: `runtime/harness/codex/hooks.json` is reached by `.codex/hooks.json`.
  Install/refresh mints normalized hashes for the authored file or refuses with
  Hooks → Trust recovery. Preparation mirrors exact trust to each literal lane
  path; relay workers carry native bypass for their opening registration hook.
  Teardown removes lane hook/project records. Inspect deleted-path residue with
  `yoke codex hook-trust sweep --dry-run`; `yoke codex hook-trust sweep` removes
  only that residue. Doctor checks current hashes for main/all lanes and sweep need.

Per-agent lifecycle hooks belong to adapter frontmatter: canonical bodies in
`runtime/agents/`, generated Claude adapters in `runtime/harness/claude/agents/`,
exposed by `.claude/agents`. Use `yoke agents render`; never hand-edit adapters.

Claude hook schema is all-or-nothing: malformed entries disable the entire
settings file. Use nested `{hooks: [{type, command}]}`, not flat `{type, command}`.
If hooks appear dead, inspect CLI startup for `Settings Error`.

`SubagentStop` frontmatter invokes local `yoke_core.domain.agent_stop` directly,
so HTTPS does not carry that auto-commit of client Git state. Harnesses using the
shared runner fall back through `SubagentStop -> session_dispatch`, which is
local-state and therefore still client-side on HTTPS.

## Fleet delivery

On a model-visible event, the hook leases pending messages for its session.
Opening and woken sessions use the same path. Settlement marks `injected` only
when aggregated output actually contains the authenticated lease token.

Whole bodies that fit are injected; oversized bodies use a stub with sender,
bounded first-line preview and `yoke messages get MESSAGE-ID`. Stored full body
is unchanged. A stub settles its envelope and wake like a full body. Sibling
budget deferral stays pending as `deferred_for_budget` for later hooks, has no
overflow-drop retry limit and raises no desktop absent-operator wake notice.
Envelope fitting belongs to decision render; raw stdout fitting to delivery.

Composition orders messages, hints, then fleet report, capped by
`yoke_contracts.hook_inline_context` and each manifest's
`session_control.inline_context_bytes`. Successive hooks drain backlog, and
file-overflow top previews cannot hide messages behind Monitor reminders.

Automatic deployment close-out failure notices name unsatisfied ids and
`yoke qa gate-summary --item PREFIX-N --target implemented`. Missing landing
notices name fields, `yoke merge item` recovery with `--result`/`--verification`,
and `yoke items get PREFIX-N body`; they avoid embedding the full refusal.

An empty inbox writes nothing. If an exact-session receipt remains pending but
nothing attaches, `session_message_delivery_probe` records the refusal phase:
`probe_session_not_deliverable`, `probe_no_leasable_receipt`, or
`probe_lease_failed` (exception class only, never message). Receipt/session/event/
reason identity folds repeated declines into the existing attempt row visible in
`yoke messages get <id>`. Unresolved hook session and non-injectable harness event
remain silent. Rationale: [undelivered envelope records its reason](archive/decisions/undelivered-envelope-records-its-reason.md).

## Parity and events

Consult [hook parity](hook-parity-map.md) before assuming equivalent surfaces.
Codex has no distinct `PostToolUseFailure`; its PostToolUse payload supplies Bash
failure telemetry. Events use `yoke_core.domain.events`; guardrails refuse
unregistered names with registry-add recovery. See [event contract](event-contract.md)
and [generated event catalog](event-catalog.md).

`agent_stop` emits `HarnessSessionStopped` with `stop_reason=completed`,
`auto_committed` (safety-net commit), or `unexpected_stop` (no clean terminal state
and no auto-commit). The same event carries item/optional task identity, final
task status and auto-commit metadata.
