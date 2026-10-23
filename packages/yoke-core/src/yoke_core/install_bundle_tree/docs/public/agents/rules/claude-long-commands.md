# Claude long commands and watcher waits

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Agents](../index.md) > [Operation homes](index.md) > Claude long commands
<!-- /yoke:breadcrumbs -->

Apply your tier; unsure means subagent.

## Main sessions

- Run `yoke watch <wrapper> --print-streaming-pair ...` first; execute its printed
  recipe: `background-wake` arms the command and tail; `in-turn` uses foreground Bash with
  `timeout: 600000`.
- Relay launches set `BASH_DEFAULT_TIMEOUT_MS=3600000` before Claude starts; subagents inherit
  it. Moved commands get one hour; a foreground timeout alone does not extend it.
  Without it, text-prompt `claude -p` kills moved calls ten minutes after the move. Have the
  launcher relaunch with the setting before a long wait; exporting inside Bash is too late.
- Explicit background Bash uses `run_in_background: true, timeout: 3600000`.
- Preserve handed-back calls and captures without duplicates. Continue until exit within
  the configured lifetime; a background-time-limit notice means
  incomplete work. Never end the turn holding an in-turn wait or poll a capture.
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
