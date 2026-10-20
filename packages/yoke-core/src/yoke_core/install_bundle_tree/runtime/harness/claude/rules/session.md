# Claude — Session Rules

Shared rules: `AGENTS.md`. Hooks, session end and recovery:
`.yoke/docs/agents/rules/claude-sessions.md`. Long commands:
`.yoke/docs/agents/rules/claude-long-commands.md`.

## Hooks and session end

- Every `settings.json` hook entry uses nested `{hooks: [{type, command}]}`. One flat entry
  disables all hooks.
- A transient SessionEnd never releases claims. On a `SESSION_ENDED` refusal, run its recovery.
- `AskUserQuestion` needs at least two options; prefer inline chat.
- Claude keeps the Bash cwd between calls (sticky cwd); still use absolute paths.

## Long commands and waits

- Main session: run `yoke watch <wrapper> --print-streaming-pair ...` first; it runs nothing.
  Run the command it prints. Unknown waits run in-turn.
- A handed-back call still runs. Reading the background task's output is how you continue the
  call, not how you end the turn: keep reading until the command exits and you have its
  outcome, because a turn that ends there kills the watcher it was holding. Never relaunch
  beside it or poll it.
- A relay-launched worker has no second chance here: prepare by naming the continuation before
  the command starts.
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
