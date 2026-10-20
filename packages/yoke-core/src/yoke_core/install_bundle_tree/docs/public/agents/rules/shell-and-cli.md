# Shell calls and CLI authority

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Agents](../index.md) > [Operation homes](index.md) > Shell and CLI
<!-- /yoke:breadcrumbs -->

## Shell calls and path authority

- Variables reset per call. Use absolute paths, `git -C ABSOLUTE_PATH`, and an explicit
  workdir or leading `cd` for relative writes.
- A work claim authorizes its lanes, main control-plane paths and `/tmp` or `/var/folders`.
  Writes to main source while you hold a lane refuse; deliberate exceptions use
  `# lint:allow-lane-main-write`. Read [lane rules](lanes-and-claims.md) first.
- Another item's lane is read-only (`foreign_lane`): use read-only `git -C LANE` verbs, `cat`,
  `ls` or native Read.
- Unresolved home paths refuse; use a literal absolute path on the executing machine.
- Remove a `mktemp -d` dir in the call that made it: `T=$(mktemp -d); trap 'rm -rf "$T"' EXIT`.
  Recursive `rm` refuses unresolved targets and shared temp-root sweeps; name the exact path.

### zsh and input hazards

- Brace `${name}:`; single-quote search patterns; put `rg` options before the pattern.
- Pass free text with backticks or `$(` through stdin or a quoted heredoc, never a
  double-quoted argument.
- Enumerate optional globs with `rg --files`; quote URLs with `?`; use `python3`; never use zsh
  `path`/`status` as variables; `mktemp` templates end in `XXXXXX`.

## Canonical yoke CLI

- Call registered function ids as `yoke <subcommand>` (dots → spaces, `_` → `-`). Runtime API
  imports, curl against the API and DB-router or service-client forms are operator-debug only.
- Install or repair the launcher per [install](../../start/install.md). Lane checks use
  `yoke dev run -- <command>`.
- Ask the narrow read (AGENTS.md "Command Output"; [help and replies](../../cli/help.md)). Registered human reads over 28,000 bytes refuse atomically; narrow them or use `--full`.
  JSON and write replies remain complete.
- Code that refuses composes through `yoke_core.domain.refusal_recovery.compose_refusal`: a
  true reason plus a reachable recovery, or the escalation owner.

## Serving floors

New function ids declare `minimum_serving_version`; an older engine refuses with
`function_version_skew`. New response fields degrade to declared earlier behavior or refuse
with a named floor; never invent defaults for required receipts.

## Shell path-use analysis

When changing shell classification, reuse `lint_shell_path_use.analyze_shell_path_use` and
`lint_payload_path_use.extract_payload_path_uses`. No second parser or broad read exception.

## Command output

- Capture non-trivial commands (tests, builds, deploys, merges, long git) to a temp file once;
  never pipe a live command to `tail` or `head`. Run `yoke <subcommand>` bare.
- Stream long commands through a `yoke watch` wrapper on the harness surface
  ([Claude](claude-long-commands.md)). A command handed back before it ends still runs:
  continue it until exit; never relaunch beside it.
- A line starting `Waiting by design:` means silence until its named bound is expected.
- Do not poll. Short sleeps before reading a registered capture refuse, and GitHub polling
  loops always refuse: after `ci wait recorded`, end the turn.
