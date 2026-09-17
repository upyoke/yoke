# /yoke do — event lineage and loop notes

Read this when auditing a routing decision, or when a loop behavior needs
its rule. The steps do not need it.

## Events

This skill relies on these structured events emitted by the shared `yoke sessions offer` path / the `/v1/session/offer` API endpoint:

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
