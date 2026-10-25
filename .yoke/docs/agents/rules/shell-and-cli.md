# Shell calls and CLI authority

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Agents](../index.md) > [Operation homes](index.md) > Shell and CLI
<!-- /yoke:breadcrumbs -->

## Shell calls and path authority

- Each call starts fresh. Use absolute paths, `git -C ABSOLUTE_PATH`, and workdir or `cd`
  for relative writes.
- Work claims cover their lanes, main control-plane paths and `/tmp` or `/var/folders`.
  Source guard excludes client-proven Git metadata; main exceptions use
  `# lint:allow-lane-main-write`. See [lane rules](lanes-and-claims.md).
- Foreign lanes are read-only (`foreign_lane`): read-only `git -C LANE`, `cat`, `ls` or Read.
- Use literal absolute paths; unresolved home paths refuse.
- Remove a `mktemp -d` dir in the call that made it: `T=$(mktemp -d); trap 'rm -rf "$T"' EXIT`.
  Name exact `rm` targets; unresolved paths and shared temp-root sweeps refuse.

### zsh and input hazards

- Brace `${name}:`; single-quote search patterns; put `rg` options before the pattern.
- Send text containing backticks or `$(` through stdin or a quoted heredoc, not double quotes.
- Enumerate optional globs with `rg --files`; quote URLs with `?`; use `python3`; never use zsh
  `path`/`status` as variables; `mktemp` templates end in `XXXXXX`.

## Canonical yoke CLI

- Call registered functions as `yoke <subcommand>` (dots → spaces, `_` → `-`). API imports,
  curl, DB-router and service-client calls are operator-debug only.
- Launcher repair: [install](../../start/install.md).
- Use [narrow reads](../../cli/help.md). Human reads over 28,000 bytes refuse: narrow, run
  an outlined `--section` command, or use `--full`. JSON and writes stay complete.
- A refusal names the true reason and a reachable recovery or escalation owner. Show refusal, timeout and crash
  diagnosis and evidence where the affected person or agent looks. Report actual effects;
  silent failure is not success, and diagnosed refusals are not raw tracebacks.

## Command output

- Capture tests, builds and deploys once to a temp file; never pipe live output to `tail`
  or `head`. Run `yoke <subcommand>` bare.
- Stream long commands with `yoke watch` ([Claude](claude-long-commands.md)). A yielded command still runs: continue until exit,
  never relaunch beside it.
- `Waiting by design:` means silence until the named bound.
- Do not poll: short sleeps before registered captures and GitHub polling loops refuse.
  After `ci wait recorded`, end the turn.
