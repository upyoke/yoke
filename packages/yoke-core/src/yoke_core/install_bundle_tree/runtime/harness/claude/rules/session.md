# Claude — Session Rules

Read `AGENTS.md` for shared rules. Before Claude hook, recovery or watcher work,
read `.yoke/docs/reference/agent-rules/claude-sessions.md`; it owns the inventory,
failure paths, session revival and identity across episodes.

Hook schema is all-or-nothing: every `settings.json` entry uses nested
`{hooks: [{type, command}]}`. One flat entry disables all hooks.

## Tool Constraints

`AskUserQuestion` needs at least 2 options; prefer inline chat for iteration.
Never Stop after arming Monitor while holding a work claim: continue the turn,
or checkpoint and `yoke sessions touch --mode parked` first. Park retains claims;
your next tool call clears it. SessionEnd on transient signals never releases
claims; follow named recovery if a command refuses `SESSION_ENDED`.

## Watcher waits

Main sessions first use `--print-streaming-pair`, which runs nothing. Run the
printed command: `background-wake` arms its command and one `yoke watch tail`
subscription; `in-turn` runs foreground with Bash `timeout: 600000`. Unknown
waits in-turn. A returned/backgrounded handle still runs: continue it until exit,
never relaunch beside it or manually poll, because a turn that ends there kills the
watcher it was holding. Reading the background task's output is how you
continue the call, not how you end the turn: keep reading until the command
exits and you have its outcome. A relay-launched worker has no second chance
here; prepare by naming the continuation before the command starts. Read the
completed raw capture once.

Subagents run long commands foreground in one Bash sequence, never
`Bash(run_in_background: true)` plus Monitor and return. Tighten dispatch if its
budget cannot fit the check. Watcher wrappers capture and classify output;
read the deep home's inventory before fallback. Relay wake digests whole to your
own visible output. Fleet mail is for actionable red gates, blockers, conflicts,
decisions and terminal results; no progress mail.

Suppression tokens (audit recorded): `# lint:no-main-check`,
`# lint:no-lifecycle-mutation-check`, `# lint:no-polling-check` override their
named guards. `# lint:no-monitor-watcher-tail-check` and
`# lint:no-raw-pytest-check` are audit-only and do NOT unblock: use minted
`yoke watch tail` and `yoke watch pytest`.

## Harness wake capability

Read the target manifest's `agent_wake` and `session_control` before choosing a
cross-harness primitive. Generated facts follow; never restate them independently.

<!-- BEGIN GENERATED: harness-wake-capability -->
Wake capability is a manifest fact, not prose. Source of truth:
`agent_wake` in `runtime/harness/<harness-dir>/manifest.json`, rendered from
`yoke_contracts.harness_wake_capability`. Change the contract and re-render; never
restate one of these facts on a document's own authority.

- `claude-code` — idle wake: supported (`Monitor`); timer wake: supported (`ScheduleWakeup`). Verified on claude-cli.
- `codex` — idle wake: none; timer wake: none. Verified on codex-cli.
- `cursor` — idle wake: supported (`notify_on_output`); timer wake: none. Verified on cursor-cli.
<!-- END GENERATED: harness-wake-capability -->
