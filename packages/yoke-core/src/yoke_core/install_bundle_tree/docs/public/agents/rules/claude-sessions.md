# Claude session rules — the deep home

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Agents](../index.md) > [Operation homes](index.md) > Claude sessions
<!-- /yoke:breadcrumbs -->

## Hook schema

Every `settings.json` hook entry uses nested `{hooks: [{type, command}]}`; one flat entry
disables all hooks. Diagnose with `yoke watch doctor -- --only project-hook-config-validity`.
Repair the whole schema, not one entry.

## Session end and recovery

- A transient SessionEnd (sleep, reload, disconnect) releases no claims, and your next hook
  event reactivates the session. No manual registration is needed.
- On a `SESSION_ENDED` refusal, run the `sessions begin` command it prints; do not guess the
  provider or model. If claims were not reacquired, run
  `yoke claims work acquire --item PREFIX-N --reason session-reactivation-recovery`.
- Physical stop needs authority: `yoke sessions terminate SESSION-ID --reason R` (read its
  `--help`). Keep a claimless session alive with `yoke sessions keepalive hold`.
- Before reporting a session dead, probe its current process; newer activity overrides a
  death record.
- Evidence for this episode only: `yoke events query --session SESSION-ID --current-episode`.
  A nonzero `elided_prior_episode_rows` means read again without the flag, not absence.

Model and refusals: [sessions model](../../sessions/model/sessions.md).

## Related

- [Claude long commands and watcher waits](claude-long-commands.md)
- [Lanes and claims](lanes-and-claims.md)
- [Shell and CLI](shell-and-cli.md)
