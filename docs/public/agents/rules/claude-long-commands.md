# Claude long commands and watcher waits

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Agents](../index.md) > [Operation homes](index.md) > Claude long commands
<!-- /yoke:breadcrumbs -->

Apply only your tier. Unsure? You are a subagent.

## Main sessions

- Ask the wrapper first: `yoke watch <wrapper> --print-streaming-pair ...` runs nothing. Run
  what it prints. `background-wake` arms the command plus one `yoke watch tail`; `in-turn` runs
  foreground with Bash `timeout: 600000`.
- A handed-back call is still running: keep reading it until it exits. Never relaunch beside
  it, never poll it, and never end the turn while you hold it.
- Only taught interruption: a local check past about one minute. Stop it cleanly, keep the
  capture as incomplete, commit and continue on CI. Never interrupt a CI watcher.
- Holding a work claim, never Stop after arming Monitor. To go quiet, run
  `yoke sessions touch --mode parked` first.
- `ci wait recorded for run N`: if the watcher stops first, end the turn; the verdict wakes you.

## Wrappers

`yoke watch --help` lists them; each `--help` owns its recipe, flags and exit codes. Prefer
`yoke watch pytest --impacted main --bounded` while iterating; the attached QA case owns the
full run. Read the raw capture once, after exit.

With no wrapper, capture to a temp file and Monitor a line-buffered progress-and-failure
filter on it. Re-read no faster than every 60 seconds. File the missing wrapper as a field note.

## Subagents

Run long commands foreground in one Bash call through completion, then read the outcome.
Never use background Bash, Monitor or `ScheduleWakeup`. If the budget cannot fit the check, the
parent dispatches tighter.

## Suppression tokens

Tokens are audit evidence, not permission. `# lint:no-polling-check` lifts only the short-sleep
check, never a GitHub polling loop. Watcher-tail, raw-pytest and subagent-background tokens
never unblock; use `yoke watch tail`, `yoke watch pytest` and foreground runs.

## Related

- [Claude session rules](claude-sessions.md)
