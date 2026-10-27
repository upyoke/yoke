# Shell and CLI authority

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Agents](../index.md) > [Operation homes](index.md) > Shell and CLI
<!-- /yoke:breadcrumbs -->

## Shell calls and path authority

- Calls start fresh. Use absolute paths, `git -C ABSOLUTE_PATH`, and workdir or `cd`
  for relative writes.
- Work claims cover their lanes, main control-plane paths and `/tmp` or `/var/folders`.
  Source guard excludes client-proven Git metadata; main exceptions use
  `# lint:allow-lane-main-write`. See [lane rules](lanes-and-claims.md).
- Reads pass anywhere the harness permits. Writes, redirects, substitutions, outputs
  and Git moves keep lane limits.
- Use literal absolute paths; unresolved homes refuse.
- Remove a `mktemp -d` dir in the call that made it: `T=$(mktemp -d); trap 'rm -rf "$T"' EXIT`.
  Name exact `rm` targets; unresolved paths and shared temp-root sweeps refuse.

### zsh and input hazards

- Brace `${name}:`; single-quote search patterns; put `rg` options before the pattern.
- Send text containing backticks or `$(` through stdin or a quoted heredoc, not double quotes.
- Enumerate optional globs with `rg --files`; quote URLs with `?`; use `python3`; never use zsh
  `path`/`status` as variables; `mktemp` templates end in `XXXXXX`.

## Canonical yoke CLI

- Run functions as `yoke <subcommand>` (dots → spaces, `_` → `-`). API imports,
  curl, DB-router and service-client calls are operator-debug only.
- Launcher repair: [install](../../start/install.md).
- Use [narrow reads](../../cli/help.md). Human reads over 28,000 bytes refuse: narrow, run
  an outlined `--section` command, or use `--full`. JSON and writes stay complete.
- Refusals name the reason and reachable recovery or owner. Show refusal, timeout, crash
  evidence where affected people or agents look. Report actual effects;
  silent failure is not success, and diagnosed refusals are not raw tracebacks.

## Command output

- Capture tests, builds and deploys once to a temp file; never pipe live output to `tail`
  or `head`. Run `yoke <subcommand>` bare.
- Stream long commands with `yoke watch` ([Claude](claude-long-commands.md)). Yielded commands still run: continue until exit,
  never relaunch beside it.
- `Waiting by design:` means silence until the named bound.
- Do not poll: short sleeps before registered captures and GitHub polling loops refuse.
