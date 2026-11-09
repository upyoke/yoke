# Claude Code

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Agents](index.md) > Claude Code
<!-- /yoke:breadcrumbs -->

Yoke supports Claude Code CLI, desktop Code, and the editor surface. Shared
project instructions come from `AGENTS.md`; Yoke skills live in
`.agents/skills/yoke/` and Claude discovers them through
`.claude/skills/yoke`. See [Native discovery](harness-discovery.md) for the
supported engine floor and configuration checks.

## Start work

Open a session in the project folder and run `/yoke onboard` after setup.
Use `/yoke steer` next to review direction and staff work. The
[command reference](commands.md) lists the other Yoke skills.

Run `yoke doctor run --session` to check this session's registration,
Claude sign-in, and permission to run Yoke commands. Follow its named recovery.
Claude can load hooks installed during a conversation on the next prompt;
the readiness check tells you whether a new session is needed.

## Sign-in and discovery

The CLI's own authentication is separate from Yoke sign-in. Check it with
`claude auth status --json`; use `claude auth login` when signed out.
Setup can find Claude's bundled CLI even when it is absent from PATH.

Keep the built-in AGENTS plugin enabled. A conflicting `CLAUDE.md` can
suppress shared instructions under Claude's default configuration; the
[discovery guide](harness-discovery.md#claude-configuration) explains how to
load both without duplicating Yoke rules.

## Messages and launches

Hooks deliver orientation and messages through the shared Yoke engine.
Supported launch, resume, and wake behavior varies by surface: the installed
`.yoke/harness/claude/manifest.json` owns those capabilities. CLI worker
launches use the CLI surface; desktop chats require operator-driven re-entry.
See [Sessions](../sessions/index.md).

## Long commands and waits

Run `yoke watch <wrapper> --print-streaming-pair ...` first, then run the
command it prints. `background-wake` arms the command and a Monitor tail;
`in-turn` runs foreground Bash with the printed timeout. `yoke watch --help`
lists the wrappers. Main sessions and subagents follow different steps; if
you are unsure which you are, follow the subagent steps.

- A Monitor defaults to five minutes. It is capped at thirty minutes in
  interactive sessions and ten in headless `-p` runs (`agent_wake` in the
  manifest). When it expires, re-arm the same tail: the command is still
  running, so never start it again beside itself.
- Relay launches set `BASH_DEFAULT_TIMEOUT_MS` and `BASH_MAX_TIMEOUT_MS` before
  Claude starts (`cli.launch_environment` in the manifest), and subagents
  inherit them. Exporting them inside Bash is too late: relaunch instead.
- An announced QA-wait cadence means silence past it is a stuck run; the
  deadline still ends the wait. With no wrapper, Monitor a filter over the
  captured progress and failures, read it at most once a minute, and file a
  note about the missing wrapper.
- Stop only a local check that has run past about one minute: stop it cleanly,
  keep its partial capture, commit and let CI run it. Never stop a CI watcher.
- To keep a claim through a stop, arm the Monitor first, then run
  `yoke sessions touch --mode parked --reason claim` as the turn's last action.
- A subagent runs foreground Bash through to the end. It never uses background
  Bash, Monitor or `ScheduleWakeup`; if the launch settings are missing, it asks
  its parent to relaunch.

## Hooks and session recovery

- Every `settings.json` hook entry uses the nested `{hooks: [{type, command}]}`
  form; one flat entry turns off all hooks. Check with
  `yoke watch doctor -- --only project-hook-config-validity` and repair the
  whole file, not one entry.
- A passing SessionEnd (sleep, reload, disconnect) releases no claims; your next
  hook event brings the session back. If your claims did not come back, run
  `yoke claims work acquire --item PREFIX-N --reason session-reactivation-recovery`.
- Stopping a session needs authority: `yoke sessions terminate SESSION-ID
  --reason R`. Keep a session with no claim alive with
  `yoke sessions keepalive hold`.
- Read evidence for this session's current episode only with
  `yoke events query --session SESSION-ID --current-episode`. A nonzero
  `elided_prior_episode_rows` means read again without the flag; it does not
  mean the events are absent.
