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
    settings.json         # Hook configuration (surfaced via .claude/settings.json symlink)
    agents/               # Rendered Claude agent adapters (yoke-*.md)
    rules/                # Claude-specific session rules
    # Hook entrypoints live under runtime.harness.hook_runner
  codex/                  # Codex adapter
    manifest.json         # Adapter manifest (identity, affordances, limitations)
    hooks.json            # Hook configuration (surfaced via .codex/hooks.json symlink)
    agents/               # Rendered Codex custom-agent adapters (yoke-*.toml)
    # Python entrypoints live under runtime.harness.codex.*
  {future-harness}/       # Future adapters follow the same pattern
    manifest.json
    agents/
    python entrypoint(s)
```

The agent adapter directories are populated by the substrate renderer (`python3 -m yoke_core.domain.agents_render`) from the canonical bodies at `runtime/agents/{agent}.md`. See [`docs/harness-substrate.md`](../../docs/harness-substrate.md) for the universal-source + per-harness-renderer model.

### Runtime floor classification

The Codex/bootstrap cluster is now Pythonized end-to-end. Entry and hook surfaces route through:

- `runtime.harness.bootstrap`
- `runtime.harness.codex.codex_entry`
- `runtime.harness.codex.codex_model`
- `runtime.harness.codex.codex_open_app`
- `runtime.harness.hook_runner` (shared dispatch entrypoint for both Claude Code and Codex)

## Required adapter parts

Every adapter implements the five parts defined in the [Harness Adapter Template](../docs/harness-adapter-template.md):

1. **Bootstrap Loader** -- loads the [Harness Bootstrap Contract](../docs/harness-bootstrap.md) startup reads
2. **Capability Manifest** -- `manifest.json` declaring identity, affordances, and substrate limitations
3. **Session-Offer Builder** -- translates identity plus shared registry support into `/yoke do` session-offer parameters
4. **Route Wrapper** -- harness-specific entry launcher (e.g. `python3 -m runtime.harness.codex.codex_entry`) providing bootstrap/identity guidance for shared operator commands
5. **Smoke-Test Matrix** -- tests for wrapper-only and hook-enhanced modes
6. **Agent Adapter Renderer Pass** -- a renderer pass under `python3 -m yoke_core.domain.agents_render` that fans the canonical bodies at `runtime/agents/{agent}.md` into the harness's native adapter shape (`.md` for Claude, `.toml` for Codex, …). Skill phase files dispatch agents through shared dispatch descriptors that name the agent by descriptor; the harness adapter handles the harness-native call. See [`docs/harness-substrate.md`](../../docs/harness-substrate.md).

## Manifest schema

See [harness-adapter-template.md](../docs/harness-adapter-template.md) section "Part 2: Capability Manifest" for the full JSON schema and field descriptions.

Key fields:
- `harness_id` -- unique identifier (e.g., `"codex"`)
- `bootstrap.spec_path` -- path to the neutral bootstrap spec JSON
- `supports.command_source` -- normally `"shared_yoke_registry"` for Yoke-owned harnesses
- `supports.disabled_entrypoints` -- shared operator commands blocked by concrete substrate limitations
- `supports.disabled_downstream_paths` -- shared delivery lanes blocked by concrete substrate limitations
- `supports.optional_local_affordances` -- hook events the harness supports (opt-in enhancements)

## Wrapper-only vs hook-enhanced mode

All adapters must work in **wrapper-only mode** -- no hooks, just the entry launcher bootstrapping orientation and emitting the identity contract for later operator commands. This is the safe default.

**Hook-enhanced mode** is optional. When the harness runtime supports hooks (e.g., Codex >= 0.118.0-alpha.2), a separate hook pack can provide additional guardrails and telemetry. Hooks are never required for correctness.

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
| Claude Code | `python3 -m runtime.harness.hook_runner SessionStart` calls `session-begin`; `python3 -m runtime.harness.hook_runner UserPromptSubmit` re-registers idempotently and renders orientation | `python3 -m runtime.harness.hook_runner SessionEnd` runs bounded `session-end-if-empty` directly | Yes (fallback) |
| Codex | `.codex/hooks.json` calls `runtime.harness.hook_runner SessionStart` | `.codex/hooks.json` calls `runtime.harness.hook_runner Stop` | Yes (fallback for claimed/stale sessions) |

Both harnesses now share the same direct Stop / SessionEnd cleanup behavior: the hook runs the existing `end_session_if_empty` domain primitive immediately under machine-config `hook_session_end_cleanup_timeout_ms` as the DB busy-wait budget. Claimless sessions end during the hook; sessions with active claims or chain-pending checkpoints stay active and rely on prompt reactivation or stale-session reclaim.

### Stale-Session Reclaim

`clean_stale_harness_sessions` is the shared janitor for both harnesses.  It:

- Derives activity as `MAX(harness_sessions.last_heartbeat, MAX(events.created_at WHERE session_id=...))` so a session that went silent on the shell heartbeat but is still emitting events is still considered fresh.
- Uses a config-tunable default TTL from machine-config `session_stale_ttl_minutes` (default 20).
- Is **executor-aware** via `EXECUTOR_STALE_TTL_OVERRIDES_MINUTES`.  Codex sessions automatically use a longer window because Codex has no true session-end event and operators routinely step away between turns — the overrides table lets us keep claimless-turn-idle alive without touching Claude Code semantics.
- Emits one `HarnessSessionStaleReclaimed` event per reclaimed session with `stale_minutes`, `last_event_at`, `released_claim_count`, `executor`, and `reason`.  Per-claim `WorkReclaimed` events still fire from `reclaim_stale_session` for audit continuity.
- Reports `skipped_between_turns` separately for Codex sessions whose activity is fresh — the janitor is never the right tool to end a Codex session between turns.

### Hook Failure Telemetry

When a Claude Code `SessionEnd`/`Stop` hook fails to complete cleanly — DB contention, cleanup exception, OS error, or missing session identity — the Python owner emits a `HarnessSessionHookFailed` event with `hook_event`, `executor`, `reason`, `latency_ms`, `stdin_state`, and `session_id_source`.  The old `>/dev/null 2>&1 || true` pattern used to swallow these failures; now the ledger carries a registered, queryable failure signal so operators can distinguish "hook never fired" from "hook blocked on stdin" from "cleanup failed".

Codex Stop stdout remains exactly `{}`. Cleanup failures are emitted through `HarnessSessionHookFailed` best-effort telemetry without writing stdout/stderr.

### Stop / SessionEnd Cleanup

`runtime.harness.hook_runner.session_end_cleanup` is a thin bounded wrapper around the existing `end_session_if_empty` domain primitive. It emits `HarnessSessionHookFailed` only when the in-process cleanup cannot complete cleanly.

Codex Stop fires at the end of every assistant turn. It is a turn-boundary cleanup, not an archive trigger: claimless sessions end, claimed or chain-pending sessions remain available for the next prompt.

## Related docs

- [Harness Bootstrap Contract](../../docs/harness-bootstrap.md) -- neutral startup expectations for all harnesses
- [Harness Adapter Template](../../docs/harness-adapter-template.md) -- five-part template with manifest schema
- [Harness Substrate](../../docs/harness-substrate.md) -- universal-source + per-harness-renderer model, session cwd binding, path-claim enforcement boundary
- [Session Offer Contract](../../docs/session-offer-contract.md) -- how offers consume harness identity
- [Hook Parity Map](../../docs/hook-parity-map.md) -- three-tier hook classification across harnesses
