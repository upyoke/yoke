# Hooks Reference

Yoke uses harness-native hook points to keep orchestration deterministic — startup orientation, tool guardrails, post-tool telemetry, and session end are all Python-owned code paths that fire without operator intervention.

## Canonical owners

| Surface | Owner |
|---|---|
| SessionStart hook (session registration, emits `HarnessSessionStarted`) | `yoke hook evaluate SessionStart` |
| UserPromptSubmit hook (startup orientation and its re-delivery, emits `HarnessSessionSentFirstUserPromptSubmit`; idempotent re-registration safety net) | `yoke hook evaluate UserPromptSubmit` |
| Session end (guarded end-if-empty; live claims or a resumable chain keep the session active) | `yoke hook evaluate SessionEnd` |
| Pre-tool guardrail deniers (Bash / DB-command lint, policy deny) — each emits `HarnessToolCallDenied` via the shared `emit_denial_event` helper before returning its deny JSON. Every rendered denial names the same registered check id the audit row records. | `yoke_core.domain.lint_db_cmd` (DB-command branches retain `lint-sqlite-cmd`; nested-Claude branches use `lint-nested-claude-cli` or `lint-remote-claude-cli`), `yoke_core.domain.lint_event_registry`, `yoke_core.domain.lint_main_commit`, `yoke_core.domain.lint_tc_label`, `yoke_core.domain.lint_write_path` |
| Pre-tool observer (emits `HarnessToolCallStarted` so PostToolUse can compute `duration_ms`) | `yoke_core.domain.observe_pre` |
| Post-tool telemetry (emits `HarnessToolCallCompleted` / `HarnessToolCallFailed` / `HarnessToolCallStructuredExit` / `HarnessLifecycleMutationDetected`, runs anomaly detection, computes `duration_ms`) | `yoke_core.domain.observe` for `PostToolUse` |
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

## Transport

`yoke hook evaluate <event>` is a thin Unix-socket client. For every non-dry
invocation it sends the event, payload, caller pid/ppid, cwd, environment, and
installed revision to one resident evaluator for the machine user. The
resident keeps the canonical engine imported and uses one persistent HTTPS
connection pool. It applies the caller context while evaluating, so session
identity and policy behavior remain those of the originating harness process.
The short-lived client reads the interpreter process start from the operating
system and stops its monotonic clock immediately before final stdout. It sends
that completion to the resident on the existing Unix socket; the resident then
adds `client_wall_ms` to the matching `HookDispatchTelemetry` context without
putting a second network request on the hook's decision path. The canonical
in-process path records the same field directly.
Inside that resident, the canonical evaluator branches on the machine config's
active connection (`yoke_cli.transport.https.resolve_https_connection`):

- **local transport** (or `--dry-run`, which always stays local): the in-process shared hook runner (`yoke_core.hooks`) dispatches the chain exactly as before.
- **https transport**: one policy chain evaluates split across the two sides. The CLI reads the hook payload once, detects the executor client-side, then (1) evaluates the `LOCAL_STATE_POLICIES` subset **client-side** via `yoke_harness.hooks.local_subset.evaluate_local_subset` — the packaged client-side policy evaluators — and (2) POSTs `{hook_schema, event_name, stdin, executor, agent_type, entrypoint, model, execution_lane, deadline_ms}` with the machine credential to the active env's `POST /v1/hooks/evaluate`, which evaluates everything else via `evaluate_remote`. The three identity fields are client-owned: the server cannot read the caller's local transcript/cache, entrypoint env, or no-project machine fallback routing inputs. Verdicts compose with **any deny wins, regardless of side**: a client deny renders immediately and skips the POST (the server verdict could not flip it); a server `outcome=denied` relays verbatim and drops client advisories (deny text is never diluted — the in-chain renderer's own rule); two allows merge stdouts via `decision_render.merge_allow_stdout` (sibling advisory envelopes join into one).

**Duplicate lifecycle dispatches collapse.** A harness may deliver one
lifecycle event twice: Claude Desktop drove `SessionStart`,
`UserPromptSubmit`, and `Stop` from two driver processes for a single
conversation while the project settings declared one command per event.
`yoke_core.hooks.dispatch_dedup` collapses the repeat before the chain
runs — same session, same event, byte-identical payload, inside
`DISPATCH_DEDUP_WINDOW_SECONDS` — and records
`HookDispatchDeduplicated`. The marker is machine-local because the
duplicate arrives in a different process, and it is scoped by run half so
the relay's client-side subset and the server's own run never read each
other's. Tool events (`PreToolUse`, `PostToolUse`, `PostToolUseFailure`,
`PermissionRequest`) are never deduplicated: each carries its own
`tool_use_id` and must run its own guardrails.

**Resident lifecycle and recovery.** The client starts the singleton on first
use. It exits after ten idle minutes, and a request from a different installed
revision makes it leave the accept loop and re-exec; the restart handshake
names both the loaded and the requested revision so a stuck upgrade reads from
one line. **Neither exit consults the telemetry queue.** Retained observations
are drained once at shutdown under their own two-second bound, and a drain that
times out warns rather than cancelling the upgrade — telemetry is disposable,
and one undeliverable batch must never pin a machine to an old revision or keep
an idle resident alive. In-flight evaluations still finish first: handler
threads are non-daemon and are joined on close. Concurrent connections evaluate
in isolated caller contexts. An unreachable socket, protocol error, startup
refusal, or mid-request crash is named on stderr and falls back to the same
canonical in-process evaluator for that invocation; `HookDispatchTelemetry`
records `evaluator=inprocess` and the fallback reason. Absence of the resident
can therefore never manufacture an allow verdict.

**The connect grace is a total budget.** `RESIDENT_CONNECT_GRACE_SECONDS`
(2s) bounds the whole phase of reaching a usable resident — connecting,
starting one, and re-trying after a restart handshake — as an absolute
deadline imposed on every socket operation those attempts make, not a glance
taken at the top of the retry loop. Once a request is under way the response
wait keeps the hook's own deadline (`YOKE_HOOK_TOTAL_TIMEOUT_MS` plus two
seconds of slack for the resident to stop itself first), measured from the
client process start so retries can never push one invocation past its own
budget. A legitimate evaluation is unaffected: at send time a healthy hook has
spent milliseconds.

**Read-only hot path.** After an HTTPS server advertises
`read_only_observation_batch_v1`, tool events whose complete canonical chains
contain no decision-making guard run locally in the resident. The classifier
comes from canonical chain ordering, not a separate allowlist; guarded tools
such as Bash, Write, and Edit remain synchronous. The first read-only event for
a session, and another at least every two seconds, still relays so pending
messages can be injected. Events between those probes return locally and queue
their unchanged `HarnessToolCallStarted`/`HarnessToolCallCompleted` and
`HookDispatchTelemetry` effects. The resident flushes the ordered queue every
two seconds or 32 observations. Session heartbeat and tool-activity state
advance when the batch commits, so their lag is bounded by the same flush
interval. An older server does not advertise the capability, leaving every
hook on the established synchronous path throughout a rolling upgrade.

**A rejected batch is dropped, not retried forever.** Delivery is ordered, so
whatever sits at the head of the queue decides whether anything behind it is
ever sent. A 4xx other than 408 or 429 means the control plane understood the
batch and will not take it, so resending the same bytes cannot succeed: the
batch is discarded and `YOKE_HOOK_TELEMETRY_BATCH_REJECTED` names the HTTP
status, the server's rejection code, and the step that fixes it. A transient
failure is retried with geometric backoff to a thirty-second ceiling for a
bounded number of attempts and then dropped the same way, and the queue length
is capped so one unreachable endpoint cannot grow the resident without limit.
While work is retained, `YOKE_HOOK_TELEMETRY_FLUSH_FAILED` carries the queue
depth and the age of its oldest entry; anything discarded is summarized as
`YOKE_HOOK_TELEMETRY_DROPPED`. Events are disposable and operational state has
its own durable owners, so no observation is worth stalling the hooks of every
session on the machine.

**One identity gate serves both hook routes.** `POST /v1/hooks/evaluate` and
`POST /v1/hooks/telemetry/batch` decide "may this payload's `session_id` act as
a Yoke session?" through the single predicate in
`yoke_core.hooks.relayed_session_identity`. They must agree, because the batch
carries payloads a live hook already relayed: when the batch route additionally
applied the conversation-alias shape test, it refused with HTTP 400 the very
payloads evaluate had accepted. Only the client can answer the question — the
machine-local Cursor session map legitimately records a conversation as its own
session, so a canonical id can equal the alias beside it — and the client
already refuses the raw case, folding an unmapped conversation to empty, which
never sets `identity_stamped`. The shape test therefore applies to unstamped
payloads only. The batch route then proves the stamp it trusts: a stamped id
whose `harness_sessions` row belongs to another actor is refused
`HOOK_OBSERVATION_SESSION_DENIED`, while an id with no row yet is accepted,
because that observation is what registers the session. That authorization is
batch-only on purpose — a false refusal there costs one disposable telemetry
batch, where the same refusal on the evaluate route would block a live tool
call on every machine at once.

**A degraded hook says which phase was slow.** When the resident cannot answer
and the canonical in-process fallback runs, the hook writes one
`YOKE_HOOK_PHASE_TIMING` line to stderr carrying `resident_wait_ms` (connect,
restart handshakes, and response wait), `fallback_ms` (the in-process
evaluation, including any synchronous telemetry reporting it performs on
completion), `client_wall_ms` (the hook process end to end), and
`fallback_reason`. A phase that was not measured reads `not-measured` rather
than zero, so a coverage gap cannot pass for an instant phase. Set
`YOKE_HOOK_PHASE_TIMING=1` to get the same line on healthy invocations. It
carries durations and one refusal code only — never a payload, an environment,
or a credential — and rendering cannot delay or fail the tool call.

Inspect the resulting timing and coverage split with `yoke sessions
hook-overhead [--hours N] [--json]`. The hook table reports PreToolUse and
PostToolUse client p50/p90/mean, evaluator p50, client-minus-evaluator
remainder, and timed/total coverage. “Evaluator” is deliberate: on hosted
transport it includes server work, while local and admin execution can happen
in-process. The tool table reports completed-call mean/p95 beside timed/total
coverage globally and per harness. Missing duration is unknown and excluded
from latency statistics; a measured zero remains timed. `ACTIVE*` is the
number of distinct sessions emitting telemetry in the fixed hour, not a live
roster or proof of simultaneous execution.

For a comparable on-demand sample, run `yoke hook benchmark --samples 5
[--json]`. It executes the harmless system `true` command between normal
PreToolUse and PostToolUse evaluations, so policy checks remain active. The
report records the harness and surface, available client/server revisions,
exact time window, run count, timing coverage, per-hook phase lines from
the durable `HookDispatchTelemetry` context, actual command time, and
whole-envelope time. The durable phase read preserves missing
`client_wall_ms` as unknown; it does not infer it from the opt-in stderr line.
Its concurrency evidence labels the live roster separately from the
running-session bucket proxy. Save `--json` output and pass it back with
`--compare REPORT.json`; differing harnesses, surfaces, revisions, commands,
or sample counts, and incomplete evaluator/client-wall coverage, are marked
incomparable rather than blended.

**Deadline contract.** One shared ceiling — `hook_runner_total_timeout_ms`, default 10000ms (`yoke_core.domain.hook_runner_deadline`) — spans both halves: the client-side subset fits within the remaining budget (head-starves-tail, identical to one in-process chain), the client's POST socket timeout is the remainder after it, `deadline_ms` propagates that same remainder, and the server stops launching further chain policies once it is exhausted (clamped to its own ceiling). A deny computed before expiry is preserved on either side; otherwise the response marks `deadline_exhausted` in `degraded` and names every skipped guard as `deadline_skipped:N:a,b,c`. Server-side latency telemetry: `yoke.hook.wait_ms` histogram + `yoke.hook.requests` counter with `outcome ∈ completed|timeout|denied` (the same `outcome` field rides the response for the client's composition).

**Failure is never harness-visible.** Timeout, unreachable host, non-200, or a non-contract body all degrade the SERVER half client-side to the event's no-op success (empty stdout, exit 0 — the same allow render the in-process runner emits) plus one stderr line naming the degradation. The client half's already-computed allow-stdout (advisories, orientation) is preserved through that degradation; a client deny never reaches it.

**A session that misses its orientation gets it on the next event.** Composing the orientation block is not the same as delivering it: a deny prints its own message in place of the merged allow stdout, and a hook the harness kills on its own timeout prints nothing at all. Either way the session has no second startup, so `yoke_core.domain.session_orientation_delivery` records the two facts separately — an *attempt* when the block is composed, a *delivery* only when the composing process survived to return an allow. An attempt with no delivery means the session is still un-oriented, and the next context-bearing event for that harness re-delivers the block once: Claude and Codex reuse their per-prompt channel, while Cursor's prompt hook answers block/allow only and moves the repair to the tool-result event (`session_orientation_redelivery_event`, following each harness manifest's `inject_events`). The repeat is labelled for the agent and named on stderr as `YOKE_ORIENTATION_REDELIVERED`, because a session that started without its bearings is otherwise invisible. The degradation path itself is unchanged — its preserved allow stdout counts as delivery.

**Local-state policies always evaluate client-side; the server evaluates the rest.** Policies whose verdict needs the client machine (client git state, bound-workspace env, on-disk file content, the hook script dir) cannot run on the server: `yoke_core.hooks.remote_policy.LOCAL_STATE_POLICIES` classifies them, the relay client evaluates exactly that subset before posting, and server-side evaluation skips each one with its module id recorded in the response's `degraded` list — the marker means "delegated to the client", not "protection off". Per-policy fail-open/fail-closed semantics are byte-identical to local transport because the client subset runs the same chain machinery. Payload-only and DB-backed policies (command-shape lints, path-claim and session-cwd guards, heartbeat, telemetry) still run server-side so the control-plane DB remains authoritative. Policies that also need one client-local fact receive a narrow `payload_extra`: main-commit gets staged Git facts, while session-cwd gets the effective client scratch root and accepts only watcher captures nested under the calling session's path. The request's `agent_type` (from `YOKE_HOOK_AGENT_TYPE` on the client) and client-owned identity fields (`entrypoint`, real `model`, `execution_lane`) merge into the payload on both sides so subagent-context detection and session registration keep working. The server binds the verified bearer-token actor to relay-registered `harness_sessions` rows (`actor_id` mirrors what local registration resolves from the machine actor).

**SubagentStop disposition.** SubagentStop is registered per-subagent in agent adapter frontmatter and invokes the `yoke_core.domain.agent_stop` owner directly — it does not route through `yoke hook evaluate`, so the https transport does not carry it. It stays local on purpose: its load-bearing work is the auto-commit of the subagent's item worktree, which is client-machine git state no server can act on. The chain registry's `SubagentStop -> session_dispatch` entry is the runner-side fallback for harnesses that route it through the shared runner; `session_dispatch` is itself classified local-state, so over https it evaluates client-side like the rest of the subset.

## Where hooks are configured

- **Claude:** `runtime/harness/claude/settings.json` — materialized as a regular `.claude/settings.json` file at the repo root. Claude composes multiple hooks on the same event; ordering in the file is preserved. Cursor can safely scan this regular file, but the entries carry their Claude-config owner marker and no-op under Cursor because `.cursor/hooks.json` is Yoke's sole Cursor hook owner.
- **Codex:** `runtime/harness/codex/hooks.json` — read via the `.codex/hooks.json` symlink at the repo root.

`yoke project install` and refresh mint Codex's normalized trust hashes for the
Yoke-authored `.codex/hooks.json`; they refuse with the Hooks → Trust recovery
when Codex config cannot be updated. Worktree preparation mirrors that exact
trust onto the lane's literal path, while relay-launched Codex workers carry
the native hook-trust bypass needed for their opening registration hook.
Worktree teardown removes the lane's hook and project records. Inspect stale
deleted-path residue with `yoke codex hook-trust sweep --dry-run`, then remove
only that residue with `yoke codex hook-trust sweep`. Doctor verifies the main
checkout and every lane against current hashes and warns when a sweep is due.

Per-agent hook wiring (for subagents with their own lifecycle hooks) lives in agent adapter frontmatter: canonical bodies in `runtime/agents/{agent}.md`, Claude-rendered adapters in `runtime/harness/claude/agents/yoke-{agent}.md` (generated by `yoke agents render`), surfaced to Claude at runtime via the `.claude/agents` symlink.

The all-or-nothing schema rule for `settings.json` still holds: any malformed entry silently disables every hook in the file. The nested `{hooks: [{type, command}]}` form is required; the flat `{type, command}` form breaks the entire file. If hooks appear dead, inspect `claude` CLI startup for `Settings Error`.

## Fleet message delivery

A hook on a model-visible event leases whatever fleet messages are pending for its session and renders them into that harness's context channel; settlement marks the receipt `injected` only once the aggregated output actually carries the lease token. There is exactly one such path, and it is told the event and the session but never whether the session is opening for the first time or reopening — which is why a woken session takes delivery on the same lease a first turn does.

Composed hook context is not chain order. Message delivery leads, hints follow, and the fleet report is last. The joined body is then capped to the harness inline ceiling in `yoke_contracts.hook_inline_context` (echoed on each harness manifest as `session_control.inline_context_bytes`). When a delivery block cannot fit, the composer injects a short pointer naming `yoke messages get` / `yoke messages acknowledge`, keeps the receipt `pending`, and records `inline_overflow` on the attempt. A harness that persists overflow to a file and previews from the top therefore cannot hide the delivery behind a Monitor reminder.

**A delivery that attaches nothing says which step declined.** Attaching no message is the ordinary outcome, so an evaluation that finds an empty inbox writes nothing. But when a receipt is `pending` for that exact session and the evaluation still attaches nothing, it records a `session_message_attempts` row against that receipt carrying the reason — `probe_session_not_deliverable` (the lease refused this session for this event), `probe_no_leasable_receipt` (a lease opened and carried nothing), `probe_lease_failed` (the lease raised, recorded by exception class, never its message), or `inline_overflow` (the body did not fit the harness inline cap). The row appears in `yoke messages get <id>` beside the wake and injection attempts, and its identity is derived from the receipt, session, event, and reason, so a repeated decline folds into the row it already wrote. Two exits stay silent by design: a session the hook process cannot name, and an event the capability table already says the harness cannot inject on. Owner: `yoke_core.domain.session_message_delivery_probe`; rationale in [`docs/archive/decisions/undelivered-envelope-records-its-reason.md`](archive/decisions/undelivered-envelope-records-its-reason.md).

## Cross-harness parity

`docs/hook-parity-map.md` classifies every hook by harness availability. Codex and Claude do not have identical hook surfaces — for example, Codex has no separate `PostToolUseFailure` event, so Bash failure telemetry is recovered from the `PostToolUse` payload directly. Consult the parity map before assuming a Claude hook also runs on Codex.

## Event emission

Hooks produce structured events in the `events` table via `yoke_core.domain.events`. Registration of new event names is enforced — the pre-tool guardrail denies unregistered event emissions and the error payload names the registry-add operation needed to register the event. See `docs/event-contract.md` for the event envelope and `docs/event-catalog.md` for the current registry (auto-generated from the DB).

### `HarnessSessionStopped`

The agent stop hook (`yoke_core.domain.agent_stop`) emits `HarnessSessionStopped` with a `stop_reason` context field. The values are:

- `completed` — the agent finished its task cleanly.
- `auto_committed` — the hook detected uncommitted work and committed it as a safety net before the agent exited.
- `unexpected_stop` — the agent exited without reaching a clean terminal state and no auto-commit fired.

Work-unit identity (`item_id` plus optional `task_num`), final task status, and auto-commit metadata ride along on the same event so session reconstruction has everything it needs in one row.
