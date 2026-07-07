---
name: do
description: "Autonomous session orchestrator — offers the session to Yoke's decision engine and routes to the chosen mode."
---

# /yoke do

Autonomous session orchestrator. Offers the current session to Yoke's decision engine, which inspects the frontier (runnable items, blocked items, SML state) and returns a `NextAction` directive. The directive is then routed to the appropriate mode handler.

After a chainable mode completes, the loop re-offers automatically up to `max_chain_steps` times.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Philosophy

**Events at every decision.** The decision engine emits `HarnessSessionOffered` and `NextActionChosen` events for a full audit trail. When investigating unexpected routing, query `yoke events query --event-name NextActionChosen --since "1 hour ago"` for the session's decision history.

**Model is server-resolved.** The model identifier is canonicalized by SessionStart (and the registration hook fallback) into the session row's model field (see your `harness_sessions` packet stanza) — including any `[variant]` suffix such as `[1m]`. The `/yoke do` loop never substitutes a model value into a command line; `session_init` reads the canonical row and `yoke sessions offer` either accepts an explicit `--model` (rare) or defaults to the same DB lookup. The LLM agent is not part of the model resolution chain.

## Steps

### 1. Resolve harness identity

Resolve the following parameters for the session offer:

- **executor**: from `$YOKE_EXECUTOR` env var, else `codex` when `CODEX_THREAD_ID` or `CODEX_MODEL` is present, else `claude-code`
- **provider**: from `$YOKE_PROVIDER` env var, else `openai` when the resolved executor is `codex`, else `anthropic`
- **lane**: resolved deterministically by the init block in `loop.md` from the core `executor_default_lane_*` config key (printed as `LANE=`). Do NOT resolve this yourself — use the value printed by the init block
- **workspace**: from `git rev-parse --show-toplevel`
- **session_id**: reuse `$YOKE_SESSION_ID` if already set; otherwise resolve from `$CLAUDE_SESSION_ID` (Claude Code) or `$CODEX_THREAD_ID` (Codex). For supported harnesses, always use the harness-provided stable ID — never auto-generate a second ID format. Reuse it for every re-offer, heartbeat, claim, and event emitted by the loop
- **Note:** Yoke-owned harnesses self-report identity only. `supported_paths` is no longer passed by the harness — Yoke core derives harness capabilities server-side from the shared registry plus manifest limitations keyed by `executor`

### 2. Call the decision engine

Read the loop logic from `.agents/skills/yoke/do/loop.md` and follow those instructions, passing the resolved harness identity parameters.

The loop handles:
- Calling `yoke sessions offer` with the resolved identity
- Parsing the `NextAction` JSON response
- Routing to the correct mode handler
- Bounded chaining for chainable actions

## Events

This skill relies on two structured events emitted by the shared `yoke sessions offer` path / the `/v1/session/offer` API endpoint:

- **HarnessSessionOffered** — Emitted by the shared offer path before decision-engine evaluation. Includes the stable session identity (executor, provider, model, lane, workspace, supported_paths) for that `/yoke do` invocation.
- **NextActionChosen** — Emitted by the shared offer path after the decision engine returns a `NextAction`. Captures the chosen action, reason, chainable flag, and correlation ID.
- **ChainStepCompleted** — Emitted after each mode handler returns. Records step, action, chainable, handler outcome, and targeted work identity. Also persists this data as a `chain_checkpoint` on the session's offer envelope (see your `harness_sessions` packet stanza) so Step C can consult durable state for the chain decision.

Canonical emission of `HarnessSessionOffered` and `NextActionChosen` lives in the shared `yoke sessions offer` path (not in `do/loop.md`). `ChainStepCompleted` is emitted via `yoke sessions checkpoint` in the loop's Step B. All harnesses produce identical event lineage.

## Notes

- The ownership adapter runs through `yoke sessions offer`. Downstream calls (`session-heartbeat`, `yoke sessions checkpoint`, claim release) resolve the session ID internally from the `YOKE_SESSION_ID` environment variable — no explicit `--session-id` argument needed.
- The `yoke sessions offer` path requires an active session (started by harness hooks or `session-begin`), heartbeats it, computes a schedule, claims ownership, and routes to the chosen mode handler.
- Only `resume` and `charge` are chainable. All other actions terminate the loop.
- `charge` dispatches from `context.scheduler.next_step`, not item type alone.
- `resume` uses claimed status first (`usher` for release work, `conduct` for implementation work, and type-aware pre-ready routing when needed).
- Epic-task resumes use `context.epic_id` / `context.task_num`; they re-enter `/yoke conduct YOK-{epic_id}` instead of relying on `item_id`.
- Max chain depth is controlled by `max_chain_steps` in machine config (default: 3).
- The loop must keep `session_id` stable across every chained step so claim/lease state can correlate correctly.
- The loop refreshes the session heartbeat while a mode handler is running so live work does not become reclaimable just because the handler takes time.
- Harness identity is resolved from environment variables (`$YOKE_EXECUTOR`, `$YOKE_PROVIDER`) with Codex fallback detection via `CODEX_THREAD_ID` / `CODEX_MODEL`, so prompt-managed Codex sessions do not silently self-report as `claude-code`. Supported paths are derived server-side from the shared registry plus manifest limitations. The model identifier is read from the session row's model field (see your `harness_sessions` packet stanza) or the canonical `hook_helpers_model.detect_model` fallback — never substituted by the LLM agent.
- Canonical `HarnessSessionOffered` / `NextActionChosen` emission is in the shared `yoke sessions offer` path, not in the loop. This ensures all harnesses produce identical event lineage regardless of whether they use `do/loop.md`.
