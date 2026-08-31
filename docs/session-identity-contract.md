# Cross-Harness Session Identity Contract

> Unified behavioral specification for session registration and identity
> surfacing across all Yoke-supported harnesses.
## Canonical Identity Sources

| Harness | Runtime source | Stable fallback source |
|-------------|---------------------|------------------------|
| Claude Code | `CLAUDE_CODE_SESSION_ID` | Hook payload `session_id` when available |
| Codex | `CODEX_SESSION_ID` (parent thread; `CODEX_THREAD_ID` names the *running* thread and is the child inside a subagent) | Hook payload `session_id` when available |
| Cursor | conversation map (`<machine-home>/cursor-session-map/`) | not an env var (`CURSOR_CONVERSATION_ID` names the conversation, not the session) |

Each runtime source belongs to exactly one harness family, and a process
reads only its own family's — a harness started from inside another
harness's shell inherits that harness's variable, so the nearest harness
ancestor in the process tree scopes every read below.

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

4. **Registration MUST bind an actor.** `harness_sessions.actor_id` names the
 person the session acts for, and every later authority read — path-claim
 registration most visibly — resolves through it. The binding is resolved once,
 at registration (`yoke_core.domain.session_actor_binding`): an explicitly
 supplied actor wins (the verified bearer-token actor over https), otherwise
 the universe's operating actor — its single human actor, or among several the
 one whose `actor_labels` row carries the machine's OS login. Every born
 universe has that actor before any session registers, so the common path is a
 lookup. Registration MUST NOT store NULL: an unresolvable actor is refused
 with a named `SESSION_ACTOR_*` reason and its recovery step, because an
 actor-less row only fails later, at a claim that cannot explain why. A row
 written before this binding existed is backfilled by its next registration
 probe, and `HC-session-actor-binding` reports and (under `--fix`) repairs the
 rows that never see one.

5. **Resolving the operating actor also converges its authority.** Binding an
 actor that holds no org role only moves the refusal one step later, to the
 first claim or path registration. So when registration resolves the operating
 actor — and only then — a single-owner universe (exactly one human actor, the
 shape a machine-local universe has and a server or hosted control plane does
 not) is granted the org `admin` role if it is missing
 (`yoke_core.domain.local_operating_actor`), the same grant birth performs.
 This is the convergence point for a universe born before the grant existed
 and upgraded in place, because nothing on that path re-enters birth. The
 explicit-actor branch converges nothing: a bearer-token control plane
 establishes its administrators through token bootstrap and sign-in, so a
 hosted registration never reaches the grant. Both readers ask whether the
 org/role tables exist before querying them — a probe inside the caller's
 open transaction must never abort it, and must never roll back to recover,
 because that discards the caller's own uncommitted work.
 `HC-local-operating-actor-authority` reports the same gap and repairs it
 under `--fix`, and a permission denial whose cause is that missing grant
 names that repair command rather than only the permission it lacked.

## Identity Read-Back Contract

Registration resolves identity once. Every later consumer READS it back
through one call and re-derives nothing:

```bash
yoke sessions identity
```

The call takes no arguments — it resolves the caller through the ambient
chain below, works on both transports (relaying rather than opening a local
database), and is available to any session at any time, not only one running
the autonomous loop. It returns session id, canonical executor and display
alias, provider, model, execution lane and that lane's permitted downstream
paths, workspace, project, actor, and `max_chain_steps`. Every field comes
from the authority, so no field is advisory and none carries a hedge.

**A session never resolves its own identity to send back.** Executor,
provider, model, and workspace are read server-side from the row; the offer
surface does not accept them, so they cannot be restated.

The execution lane is the one deliberate exception. `--lane` / request-body
`execution_lane` remains an **operator** override that routes a session to a
different lane on purpose, recorded as `SessionOfferLaneOverrideApplied`. It
is honoured faithfully, which is exactly why nothing automated may fill it
in: a lane a client guessed locally outranks the project's `session-routing`
mapping. Two Cursor sessions in one checkout showed the cost — the one whose
shell variables happened to be empty passed nothing, fell through to the
stored row, and was offered work; the one that substituted its locally
guessed lane had every frontier item filtered behind a lane name no
`lane_paths` entry declares. Same harness, same project, same workspace,
opposite outcomes. The defect was upstream of the server the whole time: the
value was fabricated locally and then passed. Identical sessions reach
identical offers because no loop resolves or sends a lane, not because the
override was removed.

**A missing row is a registration fact, not a cue to guess.** When the
authority holds no row for the calling id, the read is refused with the
recovery command. Hooks register at session start and re-register on any
later hook event, so a missing row means hook installation — never a reason
to fall back to a locally detected executor, lane, or model. A wrong value
that looks authoritative is harder to catch than a missing one: the caller
reasons correctly from a false input and nothing downstream misbehaves.

## Orientation Identity Contract

When a canonical session ID is available, every orientation block MUST include
these lines immediately after the `## Yoke Orientation` header:

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

### Registration refuses an id it cannot corroborate

"No fabricated IDs" is enforced, not just expected. `yoke sessions begin`
compares an explicitly declared `--session-id` against this process's own
ambient resolution and refuses when the two disagree
(`yoke_cli.commands.session_begin_corroboration`). A legitimate caller
always passes the id its harness gave it, so ambient resolution reproduces
it; a caller that could not resolve identity has nothing to register, and
minting an id there creates a board row for a conversation that never
existed while hiding the resolution failure that caused it.

The check is client-side by necessity: the declared id travels inside the
request envelope, so a server — especially across the https transport —
has nothing left to compare it against. Only the calling process can see
its own environment and process ancestry. Server-side marking of
unregistered-session calls (`provenance_unverified` in the dispatcher's
event context) and `HC-session-identity-provenance` are the second and
third lines of defense, not substitutes.

## Bash Propagation

Claude Code's Python-owned session-start hook appends
`export YOKE_SESSION_ID=...` to `CLAUDE_ENV_FILE` when that file path is
available. Later Bash tool calls
should prefer `YOKE_SESSION_ID` over any undocumented harness-specific
session env vars. The env stamp is the **fast path**, not the only path:
when no session env var reaches a shell (observed live on a desktop
session that received neither the env stamp nor any
SessionStart/UserPromptSubmit delivery), ambient identity still resolves
through the process-anchor registry the chain below reads. Agents never
export session env vars to self-bootstrap.

## Ambient Chain

Resolution runs one canonical chain, owned by
`yoke_core.domain.session_ambient_identity`:

1. Owning family, then that family's variables. `YOKE_SESSION_ID` wins
   outright; otherwise the nearest harness ancestor names the one family
   whose variables may answer — `CLAUDE_CODE_SESSION_ID` for Claude,
   `CODEX_SESSION_ID` then `CODEX_THREAD_ID` for Codex (parent before
   child: only the parent is registered, so a subagent reading its own
   thread id would name a session that does not exist), none for Cursor,
   which stamps none. A family that stamped nothing reachable resolves to
   `None` rather than to a variable another harness exported into this
   process; with no harness ancestor the chain is family-blind. Why:
   [`nested-harness-identity.md`](archive/decisions/nested-harness-identity.md).
2. Ancestry walk: each ancestor pid of the calling process is tested
   against the registry; a record is trusted only when the live start
   time matches (stale records are pruned best-effort).
3. `None` → mutating dispatch rejects with `actor_session_missing`, an
   infrastructure-bug signal to report — never a prompt to export env
   vars.

Step 2 reads the hook-written process-anchor registry: its record
format, the two rules that keep a pid shared by several conversations
from answering, and how a contention marker heals are documented at
[`process-anchor-registry.md`](session-identity-contract/process-anchor-registry.md).

The `actor_session_missing` rejection is the default for mutating dispatch,
but a bounded **bootstrap/config class** opts out with
`ambient_session_required=False` on its registry entry. These are the
surfaces a brand-new user or the public installer runs in a plain terminal
before any harness session exists: project install / refresh / register /
uninstall, onboarding, and the project-config writes they drive —
create/update, capability and environment settings, github binding, and
a new project's first deployment flows
(`deployment_flows.create`). A session is still bound and audited
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
idempotently calls `session-begin` when the Codex env chain or the hook payload
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
(`yoke_core.hooks.registration.ensure_registered_from_hook`).
Tool-call payloads lack SessionStart's model/source fields; the register
sequence tolerates that via the detect-* fallbacks, and concurrent
PreToolUse/PostToolUse probes are race-safe because registration is
idempotent. Remote hook evaluation (`/v1/hooks/evaluate`) runs the DB
registration half server-side, but never writes the process-anchor
registry there — the server's process context is not the caller's. The
relay client writes the anchor locally before the POST and carries the
client-only identity fields (`entrypoint`, real `model`, and — only when
this machine's own config declares a matching executor key —
`execution_lane`) on the wire so server-side registration can heal
placeholder rows without reading client-local state.

The lane is the one field the client usually has no opinion about.
Routing policy normally lives in the project's `session-routing`
capability, which only the control plane can read, so `client_lane`
answers `None` on a local miss rather than shipping a placeholder. That
placeholder would arrive as an *explicit* lane and outrank the project's
own `executor_default_lanes` mapping, stamping a session with the
unresolved sentinel — a value no `lane_paths` entry declares, which the
offer gate then treats as an unknown lane and refuses to route work on.
Defence in depth sits on the server too: `resolve_execution_lane` treats
the sentinel like `default`, so even an older client's placeholder yields
to routing policy.

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
| `yoke_core.hooks` | Claude Code, Codex | `session-start`, `user-prompt-submit`, `pre-tool-use`, `post-tool-use`, `stop`, `session-end` | Wheel-shipped hook front door for both harnesses: registration, orientation, `YOKE_SESSION_ID` propagation, backfill, and lifecycle cleanup |
| `yoke_core.api.service_client` | both | n/a | Shared session-offer / registration / claim mutation surface (`session-begin`, `session-touch`, `session-end`, `claim-work`, `release-work-claim`) |

## Test Coverage

| Test File | Covers |
|-----------|--------|
| `runtime/harness/test_hook_runner.py` | Shared hook-runner: session lifecycle, identity propagation, and cleanup behavior across both harnesses |
| `runtime/harness/test_hook_runner_register_ensure.py` | Ensure-register-on-first-sight: row probe on the flush connection, register-if-missing, runner arming (non-remote only), crash isolation |
| `runtime/harness/test_hook_runner_register_anchor.py` | Process-anchor recording inside `_register_from_hook` (transcript propagation, DB-failure independence) |
| `runtime/api/domain/test_process_ancestry.py` | Portable ancestry walk: parent-map parsing, nearest-harness matcher, pid-reuse start times |
| `runtime/api/domain/test_session_process_anchors.py` | Anchor registry: atomic writes, ancestry resolution, pid-reuse rejection + pruning, parallel-session separation |
| `runtime/api/domain/test_session_ambient_identity.py` | Canonical ambient chain order (owning family → its variables → ancestry → None) + nested-spawn regressions + CLI chokepoint delegation |
| `runtime/api/domain/test_harness_family_identity.py` | Process-tree family classification, per-family env vocabulary, and the nested-spawn chain scoping |
| `runtime/api/test_service_client.py::TestSessionOfferCommand::test_session_offer_supported_harness_requires_session_id` | Supported harnesses (`claude-code`, `codex`) must pass a canonical session id; auto-generated fallbacks are rejected at the service boundary |
| `runtime/api/test_sessions.py` | Registration idempotency and concurrent self-id isolation |
