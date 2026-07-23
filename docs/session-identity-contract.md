# Cross-Harness Session Identity Contract

> Unified behavioral specification for session registration and identity
> surfacing across all Yoke-supported harnesses..
## Canonical Identity Sources

| Harness | Runtime source | Stable fallback source |
|-------------|---------------------|------------------------|
| Claude Code | `CLAUDE_SESSION_ID` | Hook payload `session_id` when available |
| Codex | `CODEX_THREAD_ID` | Hook payload `session_id` when available |

The canonical session ID is the harness-provided stable conversation-level
identifier. It MUST NOT be inferred from the board or fabricated IDs. When the
runtime env var is absent, the hook payload `session_id` is still a valid
stable startup identity source for both harnesses and MUST trigger registration.
Any local `fallback-...` value used by Claude Code in degraded mode is not a
canonical session identity for registration or `session-offer`.

## Registration Contract

1. **Registration MUST complete before orientation output.** The `session-begin`
 call (via `service_client.py`) executes before any `printf`/`echo` that
 produces the `## Yoke Orientation` block. This ensures the scheduler sees
 the session by the time the agent processes its first prompt.

2. **Registration failure MUST be surfaced.** If `session-begin` fails (Python
 unavailable, DB locked, service error), orientation includes a visible
 warning line with the manual recovery command. The failure is never swallowed
 by `|| true`.

3. **Registration is idempotent.** Repeated calls with the same session ID
 produce no duplicate `harness_sessions` rows. This allows safe backfill from
 the prompt-submit hook and re-entry scenarios.

## Orientation Identity Contract

When a canonical session ID is available, every orientation block MUST include
these two lines immediately after the `## Yoke Orientation` header:

```
Your Session: {canonical-session-id}
Do NOT infer your identity from the active sessions table on the board.
```

The session ID is sourced from the resolved startup identity (env var first,
hook payload second), not from board parsing.

## Degraded Mode

When no stable session ID is available from either the runtime env var or the
hook payload:

| Harness | Behavior |
|-------------|----------|
| Claude Code | Uses `fallback-$$-$(date +%s)` only for local fire-once guard and `Your Session:` display; emits degraded-mode WARNING in orientation; does NOT attempt registration or call `session-offer` with that fallback |
| Codex | Emits degraded-mode WARNING in orientation; exits without registration (no fabricated IDs) |

## Bash Propagation

Claude Code's Python-owned session-start hook appends
`export YOKE_SESSION_ID=...` to `CLAUDE_ENV_FILE` when that file path is
available. Later Bash tool calls
should prefer `YOKE_SESSION_ID` over any undocumented harness-specific
session env vars. The env stamp is the **fast path**, not the only path:
when no session env var reaches a shell (observed live on a desktop
session that received neither the env stamp nor any
SessionStart/UserPromptSubmit delivery), ambient identity still resolves
through the process-anchor registry below. Agents never export session
env vars to self-bootstrap.

## Process-Anchor Registry (shell-side ambient identity)

Every registration pass through `_register_from_hook` records the hook
process's nearest harness ancestor — the per-session agent binary
(executable basename `claude` / `claude-code`), never the shared desktop
app shell — into `<machine-home>/session-anchors/<anchor-pid>.json`
(`yoke_core.domain.session_process_anchors`; atomic tmp+rename, no
locking). Each record carries `session_id`, `transcript_path` (when the
hook payload had one), `anchor_pid`, `anchor_start_time` (opaque
`ps -o lstart=` string, equality-compared to defeat pid reuse),
`anchor_process_name`, and `registered_at`. The anchor write is
best-effort and independent of DB registration success, so shell-side
identity survives a briefly unreachable control plane.

Resolution is the second step of the canonical ambient chain owned by
`yoke_core.domain.session_ambient_identity`:

1. Env chain: `YOKE_SESSION_ID` → `CLAUDE_SESSION_ID` → `CODEX_THREAD_ID`.
2. Ancestry walk: each ancestor pid of the calling process is tested
   against the registry; a record is trusted only when the live start
   time matches (stale records are pruned best-effort).
3. `None` → mutating dispatch rejects with `actor_session_missing`, an
   infrastructure-bug signal to report — never a prompt to export env
   vars.

The `actor_session_missing` rejection is the default for mutating dispatch,
but a bounded **bootstrap/config class** opts out with
`ambient_session_required=False` on its registry entry. These are the
surfaces a brand-new user or the public installer runs in a plain terminal
before any harness session exists: project install / refresh / register /
uninstall, onboarding, and the project-config writes they drive —
create/update, capability and environment settings, github binding, and
project-owned deployment-flow reconciliation
(`deployment_flows.reconcile_project`). A session is still bound and audited
when one is present, https callers stay project-scoped through the dispatch
permission gate (which enforces only once a numeric actor id is bound), and
the call is still recorded via `YokeFunctionCalled` — session-less, not
audit-less. Operator-only mutations outside the bootstrap path, including
flow-definition edits (`deployment_flows.set_status` / `update_stages`),
keep the session requirement.

Every consumer resolves through this one chain: the CLI chokepoint
(`service_client_shared_session_resolver._resolve_session_id`), the
dispatcher's identity binder, and hook helpers' `get_session_id`.
Parallel sessions in one checkout cannot collide — distinct harness
agent processes have distinct anchor pids. `--session-id` flags remain
as flagged operator-debug overrides (recorded as `session_override` in
dispatcher event context).

## Backfill

Codex `yoke hook evaluate UserPromptSubmit` (UserPromptSubmit hook)
idempotently calls `session-begin` when `CODEX_THREAD_ID` or the hook payload
`session_id` is available. This backfills
registration if the session-start hook failed or was skipped. The call remains
best-effort because prompt-submit runs on every turn and must not block the
agent, but failures are surfaced in the reminder output with the manual
recovery command.

**Ensure-register on any hook event (tool-call chain included).**
Registration MUST NOT depend on SessionStart or UserPromptSubmit firing —
tool-call hooks are the only empirically guaranteed event class. The
shared hook runner's telemetry flush probes `harness_sessions` for the
dispatching session id on its already-open connection (zero added
round-trips when registered) and drives the same `_register_from_hook`
sequence when the row is positively missing
(`runtime.harness.hook_runner_register.ensure_registered_from_hook`).
Tool-call payloads lack SessionStart's model/source fields; the register
sequence tolerates that via the detect-* fallbacks, and concurrent
PreToolUse/PostToolUse probes are race-safe because registration is
idempotent. Remote hook evaluation (`/v1/hooks/evaluate`) runs the DB
registration half server-side, but never writes the process-anchor
registry there — the server's process context is not the caller's. The
relay client writes the anchor locally before the POST and carries the
client-only identity fields (`entrypoint`, real `model`, and
`execution_lane`) on the wire so server-side registration can heal
placeholder rows without reading client-local state.

## Session Reactivation and Work Claims

When a session is reactivated — `ended_at` cleared by a subsequent `session-begin`
call after a `SessionEnd` hook ran — the `harness_sessions` row is restored to an
active state.

Two reactivation paths now coexist. Both honor the conflict semantics: a parallel
session that legitimately holds the item is never silently overwritten.

**Path A — conditional auto-reacquire (the common case).** When the prior
release was `release_reason='session_ended'` and `released_at` is inside
`session_reactivation_reacquire_window_s` (default 300s), `register_session`
inspects each prior target for a current conflicting holder. When no other
session holds an active claim on the target, a new active `work_claims` row is
inserted in the same transaction. `SessionReactivationReacquiredClaims` records
the receipt with per-target reacquired / conflict outcomes.

**Path B — advisory fall-through (the conflict case, plus out-of-window).**
When another session legitimately holds the target, OR when the release is older
than the reacquire window, no new claim row is inserted. The
`SessionReactivatedWithReleasedClaims` advisory still fires so the operator
sees what was lost; recovery is explicit (`yoke claims work acquire --item YOK-N --reason resume-recovery`).

The slim resume block (rendered by the hook runner on the next
`UserPromptSubmit` for Claude or `SessionStart` for Codex) surfaces the
outcome of either path to the operator exactly once per reactivation cycle.
`HarnessSessionResumeBlockShown` marks the render so subsequent prompts in
the same cycle do not re-render. A subsequent reactivation re-arms the block.

`/yoke do` and `/yoke charge` continue to route to the scheduler-selected
downstream skill; the slim resume block names the prior targets explicitly so
the operator can intervene whenever Path B fell through to advisory.

**Recovery for Path B (or post-window):**

```bash
yoke claims work acquire --item YOK-N --reason resume-recovery
```

Re-run this after reactivation for every item the session intends to continue
working on.  The `claim-work` call is idempotent for the same session — a
second call for an already-owned item returns `(already owned)` and exits 0.

## Implementation Files

| File | Harness | Hook Event | Role |
|------|---------|------------|------|
| `runtime/harness/hook_runner/` | Claude Code, Codex | `session-start`, `user-prompt-submit`, `pre-tool-use`, `post-tool-use`, `stop`, `session-end` | Shared hook front door for both harnesses: registration, orientation, `YOKE_SESSION_ID` propagation, backfill, and lifecycle cleanup |
| `yoke_core.api.service_client` | both | n/a | Shared session-offer / registration / claim mutation surface (`session-begin`, `session-touch`, `session-end`, `claim-work`, `release-work-claim`) |

## Test Coverage

| Test File | Covers |
|-----------|--------|
| `runtime/harness/test_hook_runner.py` | Shared hook-runner: session lifecycle, identity propagation, and cleanup behavior across both harnesses |
| `runtime/harness/test_hook_runner_register_ensure.py` | Ensure-register-on-first-sight: row probe on the flush connection, register-if-missing, runner arming (non-remote only), crash isolation |
| `runtime/harness/test_hook_runner_register_anchor.py` | Process-anchor recording inside `_register_from_hook` (transcript propagation, DB-failure independence) |
| `runtime/api/domain/test_process_ancestry.py` | Portable ancestry walk: parent-map parsing, nearest-harness matcher, pid-reuse start times |
| `runtime/api/domain/test_session_process_anchors.py` | Anchor registry: atomic writes, ancestry resolution, pid-reuse rejection + pruning, parallel-session separation |
| `runtime/api/domain/test_session_ambient_identity.py` | Canonical ambient chain order (env fast path → ancestry → None) + CLI chokepoint delegation |
| `runtime/api/test_service_client.py::TestSessionOfferCommand::test_session_offer_supported_harness_requires_session_id` | Supported harnesses (`claude-code`, `codex`) must pass a canonical session id; auto-generated fallbacks are rejected at the service boundary |
| `runtime/api/test_sessions.py` | Registration idempotency and concurrent self-id isolation |
