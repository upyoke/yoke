# Claude — Session Rules

Shared rules: `AGENTS.md`. Hooks, session end and recovery:
`.yoke/docs/agents/rules/claude-sessions.md`. Long commands:
`.yoke/docs/agents/rules/claude-long-commands.md`.

## Hooks and session end

- Every `settings.json` hook entry uses nested `{hooks: [{type, command}]}`. One flat entry
  disables all hooks.
- A transient SessionEnd never releases claims. On a `SESSION_ENDED` refusal, run its recovery.
- `AskUserQuestion` needs at least two options; prefer inline chat.
- Bash keeps sticky cwd; use absolute paths.

## Long commands and waits

- Main session: run `yoke watch <wrapper> --print-streaming-pair ...` first; it runs nothing.
  Run the command it prints. Unknown waits run in-turn.
- Relay launches set `BASH_DEFAULT_TIMEOUT_MS=3600000` before Claude starts; subagents inherit
  it. A foreground timeout alone does not extend a moved call's background lifetime.
- Explicit background Bash uses `run_in_background: true, timeout: 3600000`; subagents use
  foreground Bash. Missing launch setting: ask the launcher to relaunch before a long wait.
  Exporting inside Bash is too late. A time-limit notice means incomplete work.
- Preserve handed-back calls and captures without duplicates; use the long-command rules.
- Holding a work claim, never Stop after arming Monitor. Run `yoke sessions touch --mode parked`
  first; your next tool call clears it.
- Subagents run long commands foreground in one Bash call, never background Bash plus Monitor.

## Harness wake capability

Read the target manifest's `agent_wake` and `session_control` before choosing a cross-harness
primitive.

<!-- BEGIN GENERATED: harness-wake-capability -->
Source: `agent_wake` in `.yoke/harness/<harness-dir>/manifest.json`, from `yoke_contracts.harness_wake_capability`.

- `claude-code` — idle wake: supported (`Monitor`), each subscription ending within 30 minutes (`timeout_ms`); re-arm the same tail on the expiry notice; timer wake: supported (`ScheduleWakeup`). Verified on claude-cli.
- `codex` — idle wake: none; timer wake: none. Verified on codex-cli.
- `cursor` — idle wake: supported (`notify_on_output`); timer wake: none. Verified on cursor-cli.
<!-- END GENERATED: harness-wake-capability -->
