---
name: do
description: "Autonomous session orchestrator — offers the session to Yoke's decision engine and routes to the chosen mode."
---

# /yoke do

Autonomous session orchestrator. Offers the current session to Yoke's decision engine, which inspects the frontier (runnable items, blocked items, SML state) and returns a `NextAction` directive. The directive is then routed to the appropriate mode handler.

After a chainable mode completes, the loop re-offers automatically up to `max_chain_steps` times.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Philosophy

**Events at every decision.** The decision engine emits `HarnessSessionOffered` and `NextActionChosen` events for a full audit trail. When investigating unexpected routing, query `yoke events query --event-name NextActionChosen --since "1 hour ago"` for the session's decision history.

**Identity is server-resolved, and the loop passes none of it.** Registration resolves a session's identity once — canonical executor, display alias, provider, model (including any `[variant]` suffix such as `[1m]`), execution lane, workspace, project, actor — and writes it to the session row. `yoke sessions identity` reads it back; `yoke sessions offer` reads the same row server-side. The loop never substitutes an identity value into a command line, because a locally guessed value would *override* correct server state rather than merely duplicate it: a session that passed its own guessed lane had every frontier item filtered behind a lane name its project declares no paths for, while an otherwise identical session that happened to pass nothing was routed correctly. The offer surface still accepts `--lane`, but only as a deliberate operator re-route — never as something this loop resolves. Two sessions with the same stored row must reach the same offer, so the loop passes only the step.

## Steps

### 1. Read your session identity

Run `yoke sessions identity` as a single foreground call. It resolves the
calling session ambiently — no environment prefix, no `--session-id` — and
returns the stored identity: session id, canonical executor and its display
alias, provider, model, execution lane and the downstream paths that lane may
execute, workspace, project, actor, and `max_chain_steps`.

Every field comes from the authority, so none of it is advisory. Do not
resolve, detect, or mint any of it yourself, and do not pass any of it back
to a later call. If the read is refused because the session has no row, the
refusal names the recovery — hooks register sessions at start, so a missing
row is a hook-installation fact, not a cue to substitute a detected value.

### 2. Call the decision engine

Read the loop logic from `.agents/skills/yoke/do/loop.md` and follow those instructions.

The loop handles:
- Calling `yoke sessions offer --step N`
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

- The ownership adapter runs through `yoke sessions offer`. Every session call — `yoke sessions identity`, `yoke sessions offer`, `yoke sessions touch`, `yoke sessions checkpoint`, claim release — resolves the calling session ambiently. Do not set `YOKE_SESSION_ID` and do not pass `--session-id`; the flag is an operator-debug override only.
- The `yoke sessions offer` path requires an active session (started by harness hooks or `session-begin`), heartbeats it, computes a schedule, claims ownership, and routes to the chosen mode handler.
- Only `resume` and `charge` are chainable. All other actions terminate the loop.
- `charge` dispatches from `context.scheduler.next_step`, which the pinned
  workflow's registered skill binding produced.
- `resume` uses claimed status first and the pinned workflow's registered
  skill binding for the resumed stage.
- Epic-task resumes use `context.epic_id` / `context.task_num`; they re-enter `/yoke conduct PREFIX-{epic_id}` instead of relying on `item_id`.
- Max chain depth is `max_chain_steps`, returned by `yoke sessions identity` from machine config (default: 3).
- The loop must keep `session_id` stable across every chained step so claim/lease state can correlate correctly.
- The loop refreshes the session heartbeat while a mode handler is running so live work does not become reclaimable just because the handler takes time.
- Harness identity is resolved once at registration and read back by `yoke sessions identity`, for Claude Code, Codex, and Cursor alike. Cursor is a first-class executor (`cursor-desktop` / `cursor-cli`); its session id comes from the conversation map, never from inventing one. Do not reconstruct executor, lane, model, provider, or session id, and never mint. Supported paths are derived server-side from the shared registry plus manifest limitations.
- Canonical `HarnessSessionOffered` / `NextActionChosen` emission is in the shared `yoke sessions offer` path, not in the loop. This ensures all harnesses produce identical event lineage regardless of whether they use `do/loop.md`.
- An empty or unparseable `yoke sessions offer` response is not a no-work answer. Read back `HarnessSessionOffered` (and `FrontierStepSelected` / `WorkClaimed`) for this session before concluding the frontier is empty — see `loop.md` Step A.
