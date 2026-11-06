# Claude commands and waits

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Agents](../index.md) > [Operation homes](index.md) > Claude long commands
<!-- /yoke:breadcrumbs -->

Use your tier; unsure means subagent.

## Main sessions

- Run `yoke watch <wrapper> --print-streaming-pair ...` first; execute its printed
  recipe: `background-wake` arms the command and tail; `in-turn` uses foreground Bash with
  `timeout: 600000`.
- Monitor defaults to five minutes; its cap is thirty minutes in interactive terminal,
  desktop and editor sessions, ten minutes in headless text-prompt `-p` runs. These limits
  do not depend on plan. Recipes choose the run-mode cap from `agent_wake` in the manifest.
  Re-arm the same tail on expiry; a completed setup call is still a live subscription.
- Interactive background Bash has no time limit. Headless text-prompt `-p` defaults to ten
  minutes after backgrounding; an explicit `timeout` selects up to two hours.
- Relay launches set `BASH_DEFAULT_TIMEOUT_MS` and `BASH_MAX_TIMEOUT_MS` to the longest
  wrapper duration before Claude starts; subagents inherit them. The first covers moved
  calls and the second raises the two-hour ceiling. Read `cli.launch_environment` in the
  manifest; relaunch with those settings if missing. Exporting inside Bash is too late.
- Explicit background Bash uses `run_in_background: true` and `timeout` equal to the
  wrapper duration in milliseconds, as printed by the recipe (`--duration` for fleet).
- Preserve calls and captures without duplication; continue until exit. A background time
  limit means incomplete work. Never end an in-turn wait or poll a capture.
- Only interrupt a local check past about one minute: stop cleanly, retain its incomplete
  capture, commit and continue on CI. Never interrupt a CI watcher.
- Hold a claim: run `yoke sessions touch --mode parked --reason claim` before Stop after arming Monitor.
- `ci wait recorded for run N`: end the turn if the watcher stops first; the verdict wakes you.

## Wrappers

`yoke watch --help` lists wrappers; each `--help` owns its recipe. Iterate with
`yoke watch pytest --impacted main --bounded`; the attached QA case owns the full run.
Read raw capture once after exit. An announced QA-wait cadence means silence beyond it is
stuck; the deadline still ends the wait. Without a wrapper, Monitor a captured progress/failure
filter; read at most once per minute and file a note.

## Subagents

Run foreground Bash through completion; the launch setting above protects moved calls.
Never use background Bash, Monitor or `ScheduleWakeup`. If missing, ask the parent to relaunch.

## Suppression

Tokens never unblock watcher-tail, raw-pytest, subagent-background or GitHub polling checks.

[Session rules](claude-sessions.md)
