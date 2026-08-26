# Harness Adapters

This directory contains harness-specific adapters for integrating agent runtimes with Yoke. Each subdirectory is a complete adapter for one harness.

## What is a harness adapter?

A harness adapter is a thin layer between an agent runtime (Claude Code, Codex, a future runtime) and Yoke's core operator interface. The adapter translates harness-native mechanisms (hooks, config files, CLI wrappers) into Yoke's neutral contract surface. It does not contain business logic.

**Launchers vs shell CLIs:** The adapter entrypoints are Python launchers, not shell-native Yoke CLIs. They bootstrap orientation context and emit the identity contract that the harness should carry into later `/yoke` commands. They do not invoke internal scripts or sub-skills directly, and they do not mutate the parent shell unless you intentionally source/eval their export output.

## Directory convention

Each harness adapter lives in its own subdirectory:

```
runtime/harness/
  bootstrap-spec.json      # Shared startup-read spec (single source of truth)
  bootstrap.py             # Shared startup-read renderer
  claude/                 # Claude Code adapter
    settings.json         # Hook source materialized at .claude/settings.json
    agents/               # Rendered Claude agent adapters (yoke-*.md)
    rules/                # Claude-specific session rules
    # Hook entrypoints live under yoke_core.hooks
  codex/                  # Codex adapter
    manifest.json         # Adapter manifest (identity, affordances, limitations)
    hooks.json            # Hook configuration (surfaced via .codex/hooks.json symlink)
    agents/               # Rendered Codex custom-agent adapters (yoke-*.toml)
    # Python entrypoints live under yoke_core.hooks.*
  cursor/                 # Cursor adapter
    manifest.json         # Adapter manifest (identity, affordances, limitations)
    hooks.json            # Hook configuration (copied to the source-dev .cursor surface)
    agents/               # Rendered Cursor custom-agent adapters (yoke-*.md, surfaced via .cursor/agents)
    # Python entrypoints live under yoke_core.hooks.*
  {future-harness}/       # Future adapters follow the same pattern
    manifest.json
    agents/
    python entrypoint(s)
```

The agent adapter directories are populated by the substrate renderer (`python3 -m yoke_core.domain.agents_render`) from the canonical bodies at `runtime/agents/{agent}.md`. See [`docs/harness-substrate.md`](../../docs/harness-substrate.md) for the universal-source + per-harness-renderer model.

### Runtime floor classification

The Codex/bootstrap cluster is now Pythonized end-to-end. Entry and hook surfaces route through:

- `yoke_core.hooks.bootstrap`
- `yoke_core.hooks.codex_model`
- `yoke_core.hooks` (shared dispatch entrypoint for both Claude Code and Codex)

## Required adapter parts

Every adapter implements the six parts defined in the [Harness Adapter Template](../../docs/harness-adapter-template.md):

1. **Bootstrap Loader** -- loads the [Harness Bootstrap Contract](../../docs/harness-bootstrap.md) startup reads
2. **Capability Manifest** -- `manifest.json` declaring identity, affordances, and substrate limitations
3. **Session-Offer Builder** -- translates identity plus shared registry support into `/yoke do` session-offer parameters
4. **Route Wrapper** -- the harness-native skill or prompt surface that hands operator commands to `/yoke` (the repo-local `.agents/skills/yoke` tree both harnesses read)
5. **Smoke-Test Matrix** -- tests for wrapper-only and hook-enhanced modes
6. **Agent Adapter Renderer Pass** -- a renderer pass under `python3 -m yoke_core.domain.agents_render` that fans the canonical bodies at `runtime/agents/{agent}.md` into the harness's native adapter shape (`.md` for Claude, `.toml` for Codex, …). Skill phase files dispatch agents through shared dispatch descriptors that name the agent by descriptor; the harness adapter handles the harness-native call. See [`docs/harness-substrate.md`](../../docs/harness-substrate.md).

## Manifest schema

See [harness-adapter-template.md](../../docs/harness-adapter-template.md) section "Part 2: Capability Manifest" for the full JSON schema and field descriptions.

Key fields:
- `harness_id` -- unique identifier (e.g., `"codex"`)
- `bootstrap.spec_path` -- path to the neutral bootstrap spec JSON
- `supports.command_source` -- normally `"shared_yoke_registry"` for Yoke-owned harnesses
- `supports.disabled_entrypoints` -- shared operator commands blocked by concrete substrate limitations
- `supports.disabled_downstream_paths` -- shared delivery lanes blocked by concrete substrate limitations
- `supports.optional_local_affordances` -- hook events the harness supports (opt-in enhancements)

## Wrapper-only vs hook-enhanced mode

All adapters must work in **wrapper-only mode** -- no hooks, just the entry launcher bootstrapping orientation and emitting the identity contract for later operator commands. This is the safe default.

**Hook-enhanced mode** is optional. When the harness runtime meets the `runtime_minimums.hook_enhanced` floor declared in its `manifest.json` (e.g., `codex/manifest.json` for Codex), a separate hook pack can provide additional guardrails and telemetry. Hooks are never required for correctness.

## Environment variables

The entry launcher sets these variables for Yoke core to consume:

| Variable | Purpose | Example |
|----------|---------|---------|
| `YOKE_EXECUTOR` | Harness identity for session offers | `codex` |
| `YOKE_PROVIDER` | Model-provider identity for session offers | `openai` |
| `YOKE_MODEL` | Runtime-resolved model identifier | `gpt-5.4` |
| `YOKE_SUPPORTED_PATHS` | *(removed)* Capabilities derived server-side | — |
| `YOKE_ROOT` | Repo root (auto-detected from git) | `/path/to/yoke` |

## Session Lifecycle by Harness

Not all harnesses support the same hook events. The table below documents how each harness handles session start, end, and stale-session cleanup.

| Harness | Start Hook | End Hook | Stale Cleanup |
|---------|-----------|----------|---------------|
| Claude Code | `yoke hook evaluate SessionStart` calls `session-begin`; `yoke hook evaluate UserPromptSubmit` re-registers idempotently and renders orientation | `yoke hook evaluate SessionEnd` runs bounded `session-end-if-empty` directly | Yes (fallback) |
| Codex | `.codex/hooks.json` calls `yoke hook evaluate SessionStart` | `.codex/hooks.json` calls `yoke hook evaluate Stop` | Yes (fallback for claimed/stale sessions) |
| Cursor | `.cursor/hooks.json` maps `sessionStart` to `yoke hook evaluate SessionStart`; orientation returns through the reply's `additional_context` | `sessionEnd`/`stop` map to `yoke hook evaluate SessionEnd`/`Stop` (the IDE surface may never fire `sessionEnd` while a chat stays open) | Yes (fallback; 60-minute TTL override like Codex) |

Every harness shares the same direct Stop / SessionEnd cleanup behavior: the hook runs the existing `end_session_if_empty` domain primitive immediately under machine-config `hook_session_end_cleanup_timeout_ms` as the DB busy-wait budget. Claimless sessions end during the hook; sessions with active claims or chain-pending checkpoints stay active and rely on prompt reactivation or stale-session reclaim.

Stop also runs the promised-work gate before that cleanup. When the session holds a live work claim on a non-terminal, non-wait item and the latest main-agent final text is not an operator question, the gate holds the turn once and re-injects a reminder that names its outs (finish the step, release the claim, or stop deliberately). One reinjection without a later completed tool call is the cap; reaching it allows the turn and records `ChainEndDeferred` with `reason=reinjection_cap_reached`. Allow stdout is unchanged: Claude empty, Codex `{}`, Cursor `{}`. A hold uses each harness's continuation channel (`decision/block` on Claude and Codex, `followup_message` on Cursor) and skips cleanup until an allowed Stop. A passive additional-context envelope is not the reminder channel: Claude Stop can deliver it, but Codex Stop continuation is only `decision/block` and Cursor Stop continuation is only `followup_message`.

### Stale-Session Reclaim

`clean_stale_harness_sessions` is the shared janitor for both harnesses.  It:

- Derives activity from first-class session heartbeat, active-claim timestamps, and `harness_sessions.last_tool_call_at`; the events ledger remains telemetry rather than liveness state.
- Uses `session_stale_ttl_minutes` (default 20) for sessions with no active holdings and `session_stale_ttl_with_holdings_minutes` (default 240) for sessions holding a work claim, session-owned strategy-document claim, or session-owned coordination lease.
- Is **executor-aware** via `EXECUTOR_STALE_TTL_OVERRIDES_MINUTES`.  Codex sessions automatically use a longer window because Codex has no true session-end event and operators routinely step away between turns — the overrides table lets us keep claimless-turn-idle alive without touching Claude Code semantics.
- Emits one `HarnessSessionStaleReclaimed` event per reclaimed session with `stale_minutes`, `last_event_at`, `released_claim_count`, `executor`, and `reason`.  Per-claim `WorkReclaimed` events still fire from `reclaim_stale_session` for audit continuity.
- Grounds "in flight" in evidence that is still current. An unfinished `session_tool_calls` row only counts while it is the session's newest recorded activity; once the session records activity after the call opened, the row is residue from a harness that never wrote its completion and no longer shields the session. Without that grounding a harness that never closes its rows makes every one of its sessions permanently unreclaimable, whatever its executor.
- Reports `skipped_between_turns` for any session the sweep spared even though the base threshold had elapsed — by an executor TTL override, or by live in-flight evidence. The bucket answers "why was this one left alone?", so a session still inside the base threshold is simply fresh and is not listed. No executor is special-cased: the janitor is never the right tool to end a session between turns, on any harness.
- Clears the session's chain checkpoint as part of the reclaim: chain budget is a live session's to spend, so a collected session's leftover checkpoint can no longer refuse later end attempts with `chain_pending`. The `HarnessSessionStaleReclaimed` event reports `chain_checkpoint_cleared` and `chain_checkpoint_step`.

### Hook Failure Telemetry

When a Claude Code `SessionEnd`/`Stop` hook fails to complete cleanly — DB contention, cleanup exception, OS error, or missing session identity — the Python owner emits a `HarnessSessionHookFailed` event with `hook_event`, `executor`, `reason`, `latency_ms`, `stdin_state`, and `session_id_source`.  The old `>/dev/null 2>&1 || true` pattern used to swallow these failures; now the ledger carries a registered, queryable failure signal so operators can distinguish "hook never fired" from "hook blocked on stdin" from "cleanup failed".

Codex Stop stdout remains exactly `{}`. Cleanup failures are emitted through `HarnessSessionHookFailed` best-effort telemetry without writing stdout/stderr.

### Stop / SessionEnd Cleanup

`yoke_core.hooks.session_end_cleanup` is a thin bounded wrapper around the existing `end_session_if_empty` domain primitive. It emits `HarnessSessionHookFailed` only when the in-process cleanup cannot complete cleanly.

Codex Stop fires at the end of every assistant turn. It is a turn-boundary cleanup, not an archive trigger: claimless sessions end, claimed or chain-pending sessions remain available for the next prompt.

## Related docs

- [Harness Bootstrap Contract](../../docs/harness-bootstrap.md) -- neutral startup expectations for all harnesses
- [Harness Adapter Template](../../docs/harness-adapter-template.md) -- five-part template with manifest schema
- [Harness Substrate](../../docs/harness-substrate.md) -- universal-source + per-harness-renderer model, session cwd binding, path-claim enforcement boundary
- [Session Offer Contract](../../.yoke/docs/reference/session-offer.md) -- how offers consume harness identity
- [Hook Parity Map](../../docs/hook-parity-map.md) -- three-tier hook classification across harnesses
