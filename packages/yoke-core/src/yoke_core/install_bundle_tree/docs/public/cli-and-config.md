# CLI and config

## CLI

After install, `yoke` is on PATH and always runs the **main checkout's**
installed packages (not a linked worktree's source), unless you re-point the
editable install for source-dev.

Common operators:

```bash
yoke status
yoke onboard
yoke ui
yoke items get PREFIX-N
yoke items get PREFIX-N body
yoke board rebuild --print-only
yoke doctor
```

Harness skills (`/yoke do`, `/yoke idea`, …) call the same function-call
surface; CLI adapters are the operator/debug shape. Prefer
`yoke <subcommand> --help` for flags.

## Machine config

`~/.yoke/config.json` holds machine-local connections and tunables: which
environment is active, API URLs, local paths. Secrets for capabilities live
under `~/.yoke/secrets/` (not in the repo).

`preferred_session_models` is the surface-to-model map yoke-launched
sessions consult when create carries no explicit `--model`. Precedence:
explicit `--model` > this map > the vendor default. Model availability is
bound to the accounts on this machine, so the map stays machine-local.
A fresh installer/onboard write seeds the real key with every launchable
harness surface from the session-control registry, each set to a blank
string. Blank (or whitespace) means unset: the resolver and
`--list-models` treat it like an absent entry and fall through to the
vendor default. Activation is typing a model id into a blank. Existing
maps are left untouched; machines without the key are not backfilled
except on a fresh write or an explicit config repair.
`yoke status` and `yoke session-control launch create --list-models`
name the key and the config file. Every launch path — operator create and
any later worker launcher — must call the same resolver.

## Launched sessions run unattended

A session the launch plane starts is an autonomous worker with nobody
watching its terminal, so every launch and every wake engages the harness
permission bypass: Claude Code is launched with
`--dangerously-skip-permissions`, Codex with approvals and sandbox bypassed
(`--dangerously-bypass-approvals-and-sandbox` on the CLI route, the same
posture as thread parameters on the app-server route), and Cursor with
`--force` alongside `--trust` on the CLI route. Cursor's ACP launch route
takes no such flag: the relay answers each permission request itself and
owns the terminals commands run in, so it is unattended already. This is
unconditional for launched sessions and changes nothing about a session you
start yourself.

One native gate can still refuse: Claude Code declines a bypassed background
launch until the machine has accepted the bypass disclaimer once. The launch
reports `permission_bypass_unaccepted` with the recovery step — run
`claude --dangerously-skip-permissions` interactively on that machine, accept
the prompt, then retry.

## Connections

A connection is how this machine reaches a universe:

- **local-postgres** — in-process against a local DB
- **https** — relay to Cloud or self-hosted API

`yoke status` shows which connection is active.

## Local UI

```bash
yoke ui
```

Serves the same universe workbench used on Cloud, against your active
connection (typically `http://127.0.0.1:8688`).

## Project-local `.yoke/`

Installed into each managed repo: skills, agent adapters, hooks, policy,
and `.yoke/docs` (this public corpus). Board markdown under `.yoke/BOARD.md`
is a generated view — do not hand-edit it as source of truth.
