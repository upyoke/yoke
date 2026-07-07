# Hooks Reference

Yoke uses harness-native hook points to keep orchestration deterministic — startup orientation, tool guardrails, post-tool telemetry, and session end are all Python-owned code paths that fire without operator intervention.

## Canonical owners

| Surface | Owner |
|---|---|
| SessionStart hook (session registration, emits `HarnessSessionStarted`) | `yoke hook evaluate SessionStart` |
| UserPromptSubmit hook (first-prompt orientation, emits `HarnessSessionSentFirstUserPromptSubmit`; idempotent re-registration safety net) | `yoke hook evaluate UserPromptSubmit` |
| Session end (guarded end-session path, claim release) | `yoke hook evaluate SessionEnd` |
| Pre-tool guardrail deniers (Bash / DB-command lint, policy deny) — each emits `HarnessToolCallDenied` via the shared `emit_denial_event` helper before returning its deny JSON. `lint_sqlite_cmd` remains a legacy stable module id for compatibility. | `yoke_core.domain.lint_db_cmd` (emits legacy stable id `lint-sqlite-cmd`), `yoke_core.domain.lint_event_registry`, `yoke_core.domain.lint_main_commit`, `yoke_core.domain.lint_tc_label`, `yoke_core.domain.lint_write_path` |
| Pre-tool observer (emits `HarnessToolCallStarted` so PostToolUse can compute `duration_ms`) | `yoke_core.domain.observe_pre` |
| Post-tool telemetry (emits `HarnessToolCallCompleted` / `HarnessToolCallFailed` / `HarnessToolCallStructuredExit` / `HarnessLifecycleMutationDetected`, runs anomaly detection, computes `duration_ms`) | `yoke_core.domain.observe` for `PostToolUse` |
| DB error annotation | `yoke_core.domain.db_error_hook` |
| Agent stop (claim drain, HarnessSessionStopped) | `yoke_core.domain.agent_stop` |
| Emergency status repair | `yoke_core.engines.repair_status` |

The `yoke hook evaluate` CLI is the stable boundary project hook configs call; the spelling is identical on every transport. Other Python modules above are internal policy/telemetry owners executed behind the runner, not copy-paste hook config commands.

## Transport

`yoke hook evaluate <event>` branches on the machine config's active connection (`yoke_cli.transport.https.resolve_https_connection`):

- **local transport** (or `--dry-run`, which always stays local): the in-process shared hook runner (`runtime.harness.hook_runner`) dispatches the chain exactly as before.
- **https transport**: one policy chain evaluates split across the two sides. The CLI reads the hook payload once, detects the executor client-side, then (1) evaluates the `LOCAL_STATE_POLICIES` subset **client-side** via `yoke_harness.hooks.local_subset.evaluate_local_subset` — the packaged client-side policy evaluators — and (2) POSTs `{hook_schema, event_name, stdin, executor, agent_type, entrypoint, model, execution_lane, deadline_ms}` with the machine credential to the active env's `POST /v1/hooks/evaluate`, which evaluates everything else via `evaluate_remote`. The three identity fields are client-owned: the server cannot read the caller's local transcript/cache, entrypoint env, or no-project machine fallback routing inputs. Verdicts compose with **any deny wins, regardless of side**: a client deny renders immediately and skips the POST (the server verdict could not flip it); a server `outcome=denied` relays verbatim and drops client advisories (deny text is never diluted — the in-chain renderer's own rule); two allows merge stdouts via `decision_render.merge_allow_stdout` (sibling advisory envelopes join into one).

**Deadline contract.** One shared ceiling — `hook_runner_total_timeout_ms`, default 3000ms (`runtime.harness.hook_runner.deadline`) — spans both halves: the client-side subset fits within the remaining budget (head-starves-tail, identical to one in-process chain), the client's POST socket timeout is the remainder after it, `deadline_ms` propagates that same remainder, and the server stops launching further chain policies once it is exhausted (clamped to its own ceiling). A deny computed before expiry is preserved on either side; otherwise the response marks `deadline_exhausted` in `degraded`. Server-side latency telemetry: `yoke.hook.wait_ms` histogram + `yoke.hook.requests` counter with `outcome ∈ completed|timeout|denied` (the same `outcome` field rides the response for the client's composition).

**Failure is never harness-visible.** Timeout, unreachable host, non-200, or a non-contract body all degrade the SERVER half client-side to the event's no-op success (empty stdout, exit 0 — the same allow render the in-process runner emits) plus one stderr line naming the degradation. The client half's already-computed allow-stdout (advisories, orientation) is preserved through that degradation; a client deny never reaches it.

**Local-state policies always evaluate client-side; the server evaluates the rest.** Policies whose verdict needs the client machine (client git state, bound-workspace env, on-disk file content, the hook script dir) cannot run on the server: `runtime.harness.hook_runner.remote_policy.LOCAL_STATE_POLICIES` classifies them, the relay client evaluates exactly that subset before posting, and server-side evaluation skips each one with its module id recorded in the response's `degraded` list — the marker means "delegated to the client", not "protection off". Per-policy fail-open/fail-closed semantics are byte-identical to local transport because the client subset runs the same chain machinery. Payload-only and DB-backed policies (command-shape lints, path-claim and session-cwd guards, heartbeat, telemetry) run server-side as-is — the control-plane DB is the server's own authority. The request's `agent_type` (from `YOKE_HOOK_AGENT_TYPE` on the client) and client-owned identity fields (`entrypoint`, real `model`, `execution_lane`) merge into the payload on both sides so subagent-context detection and session registration keep working. The server binds the verified bearer-token actor to relay-registered `harness_sessions` rows (`actor_id` mirrors what local registration resolves from the machine actor).

**SubagentStop disposition.** SubagentStop is registered per-subagent in agent adapter frontmatter and invokes the `yoke_core.domain.agent_stop` owner directly — it does not route through `yoke hook evaluate`, so the https transport does not carry it. It stays local on purpose: its load-bearing work is the issue-flow auto-commit of the subagent's worktree, which is client-machine git state no server can act on. The chain registry's `SubagentStop -> session_dispatch` entry is the runner-side fallback for harnesses that route it through the shared runner; `session_dispatch` is itself classified local-state, so over https it evaluates client-side like the rest of the subset.

## Where hooks are configured

- **Claude:** `runtime/harness/claude/settings.json` — read via the `.claude/settings.json` symlink at the repo root. Claude composes multiple hooks on the same event; ordering in the file is preserved.
- **Codex:** `runtime/harness/codex/hooks.json` — read via the `.codex/hooks.json` symlink at the repo root.

Per-agent hook wiring (for subagents with their own lifecycle hooks) lives in agent adapter frontmatter: canonical bodies in `runtime/agents/{agent}.md`, Claude-rendered adapters in `runtime/harness/claude/agents/yoke-{agent}.md` (generated by `yoke agents render`), surfaced to Claude at runtime via the `.claude/agents` symlink.

The all-or-nothing schema rule for `settings.json` still holds: any malformed entry silently disables every hook in the file. The nested `{hooks: [{type, command}]}` form is required; the flat `{type, command}` form breaks the entire file. If hooks appear dead, inspect `claude` CLI startup for `Settings Error`.

## Cross-harness parity

`docs/hook-parity-map.md` classifies every hook by harness availability. Codex and Claude do not have identical hook surfaces — for example, Codex has no separate `PostToolUseFailure` event, so Bash failure telemetry is recovered from the `PostToolUse` payload directly. Consult the parity map before assuming a Claude hook also runs on Codex.

## Event emission

Hooks produce structured events in the `events` table via `yoke_core.domain.events`. Registration of new event names is enforced — the pre-tool guardrail denies unregistered event emissions and the error payload names the registry-add operation needed to register the event. See `docs/event-contract.md` for the event envelope and `docs/event-catalog.md` for the current registry (auto-generated from the DB).

### `HarnessSessionStopped`

The agent stop hook (`yoke_core.domain.agent_stop`) emits `HarnessSessionStopped` with a `stop_reason` context field. The three values are:

- `completed` — the agent finished its task cleanly.
- `auto_committed` — the hook detected uncommitted work and committed it as a safety net before the agent exited.
- `unexpected_stop` — the agent exited without reaching a clean terminal state and no auto-commit fired.

Agent context (epic/task references, final task status, auto-commit metadata) rides along on the same event so session reconstruction has everything it needs in one row.
