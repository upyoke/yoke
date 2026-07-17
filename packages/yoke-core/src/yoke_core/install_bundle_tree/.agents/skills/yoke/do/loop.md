# /yoke do — Bounded Chaining Loop

This file contains the loop logic for `/yoke do`. It is read and executed by the main SKILL.md.

## Constants

- `MAX_CHAIN_STEPS` — Read from machine config key `max_chain_steps` (default: 3). Resolved once in the init block and reused for all chain decisions.
- Chainable actions: `resume`, `charge` (as indicated by the `chainable` field in the response).

## Loop Procedure

Execute the following loop, starting at `step = 1`:

### Step A: Call the Decision Engine

Initialize a stable session id and resolve harness identity once per `/yoke do`
invocation and reuse them on every loop iteration.

**IMPORTANT — cross-invocation variable persistence:** Shell
variables set via `export` in one Bash tool call do NOT persist to subsequent
Bash tool calls. After running this block, **capture the printed
`YOKE_SESSION_ID` and `_workspace` values in your prompt context** and
substitute them as literal strings in all later Bash calls (Steps B, C, D).
Never reference `$YOKE_SESSION_ID` or `$_workspace` in a later Bash call
expecting them to survive from this one — they won't.

**Session-ID resolution:** Downstream session wrappers
(`session-heartbeat`, `yoke sessions checkpoint`, `yoke sessions checkpoint-read`,
claim release) resolve the session ID internally from the `YOKE_SESSION_ID`
environment variable — no explicit `--session-id` needed. Only the session
establishment call (`yoke sessions begin`, invoked internally by the init
wrapper) and `yoke sessions offer` pass `--session-id` explicitly (for
establishment and validation). Set `YOKE_SESSION_ID` in each Bash call's
environment using the literal value captured from the init output.

Run `yoke sessions init` as a single foreground call. The client-local wrapper
uses the interpreter that owns the installed `yoke` command, so packaged
installs never depend on an ambient shell Python carrying Yoke modules.
The wrapper owns all session identity resolution + the idempotent session
establishment call internally. Establishment routes through the
transport-keyed `yoke sessions begin` adapter, which is connection-keyed
exactly like `yoke sessions offer`: an https active connection relays the
registration to the connected server (so a prod-over-https bootstrap
registers on that authority), while a non-prod local-postgres connection
dispatches in-process. It also resolves the canonical
model from the session row's model field (see your `harness_sessions`
packet stanza, preserving any `[variant]` suffix written by SessionStart)
and falls back to `runtime.harness.hook_helpers_model.detect_model` on a
cold-start cache miss — the LLM agent never substitutes a model value.
The wrapper writes `KEY=VALUE` lines to stdout; capture each value into
your prompt context for substitution into later Bash calls.

```bash
yoke sessions init
```

The wrapper emits these keys, one per line, in stable order:

- `SESSION_ID` — resolved `YOKE_SESSION_ID` (existing env, harness-mapped, or generated)
- `WORKSPACE` — git toplevel of the calling cwd
- `LANE` — resolved execution lane (advisory; server anchors on session row)
- `EXECUTOR` — `claude-code` | `codex` | (custom from `YOKE_EXECUTOR`)
- `PROVIDER` — `anthropic` | `openai` | (custom from `YOKE_PROVIDER`)
- `MODEL` — the canonical model id resolved from the session row's model field (see your `harness_sessions` packet stanza) / `detect_model` fallback
- `MAX_CHAIN_STEPS` — read from machine config (default `3`)

The wrapper exits non-zero if the cwd is not inside a git repository or if
`yoke sessions begin` fails; on failure it forwards the underlying handler's
actionable message (missing project id, transport misconfiguration,
`SessionError`) to stderr before the exit-code line. Otherwise it exits 0
and the printed values are stable for the duration of the `/yoke do`
invocation.

Run the registered `yoke sessions offer` wrapper to get a `NextAction`. The shared offer path
emits canonical `HarnessSessionOffered` and `NextActionChosen` events internally --
the loop does not emit these events directly.

The session MUST already be active before calling `yoke sessions offer` (created by
the `yoke sessions begin` establishment call above). The offer path validates,
heartbeats, schedules, and claims — it does NOT create sessions.

This MUST run in the **same Bash call** as the init block above (or substitute
`{_executor}`, `{_provider}`, `{_lane}`, and `{_workspace}` with literal
values captured from the init output, and set `YOKE_SESSION_ID` in the
environment):

```bash
# FR-7: No --supported-paths. Server derives capabilities from shared registry plus manifest limitations.
# `--lane` is advisory only; server anchors on the session row.
# Passing the resolved value (or `default`) is harmless — passing a literal
# `primary` against an executor whose default is `DARIUS`/`ALTMAN` would
# emit a `SessionOfferLaneOverrideIgnored` WARN event without changing the
# routing outcome.
yoke sessions offer \
 --executor "$_executor" \
 --provider "$_provider" \
 --workspace "$_workspace" \
 --lane "$_lane" \
 --session-id "$YOKE_SESSION_ID" \
 --step "{step}"
```

The assembled command must literally include `--session-id "$YOKE_SESSION_ID"`
so every re-offer stays attached to the stable session identity begun at the
start of the `/yoke do` invocation.

Where `{lane}` is the resolved value from the parent SKILL.md.

Parse the JSON from stdout **in the prompt context** — do not capture it into a shell variable (`_offer=$(...)`) and do not pipe it to a parser (`| python3 -c ...`); the harness renders the command's stdout to the next turn and you read it inline. Bare invocation + prompt-context parsing is the canonical shape, the same as `yoke sessions ownership-guard` at `loop-routing.md` Step B. The response has this shape:

```json
{
 "action": "resume|charge|feed|strategize|wait|escalate",
 "reason": "Human-readable explanation",
 "chainable": true|false,
 "correlation_id": "session-id",
 "context": { ... }
}
```

`yoke sessions offer` itself does not need `--model` — it resolves the canonical
model from the session row's model field (same DB row `yoke sessions begin`
populated above; see your `harness_sessions` packet stanza) with the
`detect_model` fallback.

If the command exits non-zero, report the error and stop.

**Note:** Canonical `HarnessSessionOffered` and `NextActionChosen` events are emitted by the shared offer path (via `yoke sessions offer` / the `/v1/session/offer` API endpoint), not by this loop. Pass the current `{step}` number to that shared path so it can attach the same loop iteration to both events while centrally handling indexed `item_id` / `task_num` population and merged action-specific context.

### Step B: Route to Mode Handler

Read [`loop-routing.md`](loop-routing.md) for the full routing rules, heartbeat management, checkpoint persistence, and all action-specific handlers (`resume`, `charge`, `escalate`, `feed`, `strategize`, `wait`).

### Step C: Chain Decision

Read [`loop-followups.md`](loop-followups.md) for the chain decision logic, session cleanup (Step D), and error handling.
