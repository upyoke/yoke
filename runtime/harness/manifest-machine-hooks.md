# Harness manifest: machine hooks

The `machine_hooks` object of [`manifest.json`](manifest-schema.md) is rendered
from `yoke_contracts.harness_machine_hooks.HARNESS_MACHINE_HOOKS`. It names
where the harness reads user-level hooks and which events Yoke installs there,
so a session opened outside any Yoke project still registers, receives
messages and runs the machine-scope Bash guards.

Setup and project install or refresh write these entries; every Yoke hook
re-checks its own harness's file and rewrites it only when it differs;
`yoke uninstall` removes them; `yoke doctor` reports their state as
`HC-machine-hooks`. A harness whose home folder is absent is not installed
here: nothing is written and the result names `<harness>_not_installed`.

| Key | Type | Description |
|-----|------|-------------|
| `source` | string | Canonical Python contract that owns the fact. |
| `user_config_path` | string | The user-level hooks file, as written to a person. |
| `home_env` | string \| null | Environment variable that overrides the harness home (`CODEX_HOME`), or null. |
| `config_owner` | string | `YOKE_HOOK_CONFIG_OWNER` value every installed command carries. |
| `project_configs` | array | Project-relative configs whose Yoke entries make the user-level hook step aside. |
| `project_config_search` | string | `project_dir` reads the folder the harness opened; `ancestors` reads each folder up to the repository root. |
| `events` | array | `{native_event, verb, matcher?}` entries installed in the user config. |
| `trust` | string | `none`, or `codex_trusted_hash` when the harness runs a hooks file only after trusting each handler. |
| `deferrals` | array | Events the harness offers that the set leaves out on purpose, each with its reason. |

## Step-aside rule

`yoke hook evaluate` reads `config_owner` before evaluating anything. When the
harness's project config for the session folder holds any non-machine-wide
`yoke hook evaluate <Verb>` entry for the same native event, the user-level
invocation exits as a no-op, for tool events too. Exactly one Yoke evaluation
then runs per native event, so composed context is delivered once. A project
file the harness would reject owns nothing.

Cursor also fires imported Claude hook configs, including the user-level
`~/.claude/settings.json`. The imported user-level Claude hook steps aside on
any event Cursor's own project or user config owns, tool events included,
because Cursor fires both (measured on cursor-agent 2026.10.16-e3cb207). An
imported project-level Claude hook steps aside only on the events Cursor fires
on both configs.

## Trust and failures

Codex trust covers only the handlers Yoke wrote; a person's own handlers keep
their trust standing, and Yoke's entries go last so those positions never
move. Trust is keyed by the hooks file under its resolved folder, because
Codex resolves a symlinked home before matching it (codex-cli 0.161.0).
Codex runs hooks only with `[features] hooks = true` in its `config.toml`. A user config that is not valid hook JSON is never overwritten: setup
and doctor name `machine_hooks_config_malformed`, the path, and the recovery
(fix or move the file, then run `yoke setup` again).
