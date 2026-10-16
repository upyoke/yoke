# Machine config and native models

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [CLI and config](index.md) > Machine config and native models
<!-- /yoke:breadcrumbs -->

Select machine-local configuration, inspect native model availability and read
how unattended launches use harness permissions.

## Machine config

`~/.yoke/config.json` holds machine-local connections and tunables: which
environment is active, API URLs, local paths. Secrets for capabilities live
under `~/.yoke/secrets/` (not in the repo).

For an isolated machine config, select its home before running a writer:

```bash
YOKE_MACHINE_HOME=/tmp/yoke-worker yoke env use local
```

Configure `local` in that home first. `YOKE_MACHINE_HOME` selects
`config.json` inside that directory and takes precedence over
`YOKE_MACHINE_CONFIG_FILE`. Without a home override, the config-file variable
selects a file; a relative value anchors under `~/.yoke`, then the default is
`~/.yoke/config.json`. `--config` selects an explicit file; relative values
anchor under the selected machine home.

Writers refuse `machine_config_not_owned` when the target differs from the
selected config or resolves outside an explicit `YOKE_MACHINE_HOME`, including
through a symlink. Remove `--config` and retry with the selected config.
This check runs before config
locking or credential changes; readers may inspect an explicit foreign file.

Relay-launched sessions discard an inherited `YOKE_MACHINE_CONFIG_FILE` for
all harnesses and surfaces. They retain the selected machine home, and their
child processes inherit that environment. An explicit launcher environment
may select a shared config; set its machine home consistently. An isolated
worker never uses a steering machine's config-file override implicitly.

The `projects` list stores one checkout per project on this machine:

```json
{"projects": [{"checkout": "/work/my-project", "project_id": 7}]}
```

Register it once with `yoke project register /work/my-project --project-id 7`.
Checkout lookup does not depend on `--env`, `YOKE_ENV`, or `active_env`;
Every configured connection uses the same entry.
Removing a connection keeps project checkouts. Moving an occupied project's
checkout requires `--reassign` from a session holding that project's live
steering seat; the CLI confirms it with `yoke claims steering verify`.
The config supports only this list shape and these two entry fields.


The installer records `settings.distribution` as `{"origin": "https://api.upyoke.com",
"channel": "stable"}` using the actual install selection. `yoke update` requires
that record and uses it in a fresh shell. Select or repair it explicitly with
`yoke config distribution set --origin URL --channel NAME`; run that command's
`--help` for flags. This does not change the active control-plane connection.
Relays connected to a private API host also require this record and install
from `origin/simple/`; they do not infer an index from the API host. See
[Maintaining a private fork](../projects/private-forks.md) for artifacts and recovery.

Launch model choice does not live in machine config. A launch names a level
(`--level LEVEL`) and Yoke places it on one of that level's options — see
[launching by level](../agents/level-launches.md#launching-by-level) —
or names an exact selection with `--surface` and the knobs below, recorded as
an override. A knob an explicit launch leaves unnamed takes the surface's
vendor default. Preview combines equal requested/effective settings and shows
both when they differ, with each knob's source (`level SENIOR option`,
`explicit launch request`, or `vendor default`). Empty rows are omitted;
`--json` retains the complete record. The bound session shows
the effective ask beside provider-attested served facts. A machine file that
still carries a retired launch-default key keeps loading; `yoke status` warns
`machine_config_key_retired`, and the next config write removes the key.

`yoke session-control launch preview --model M` reports each machine's quota
in the pool `M` actually bills to, under `REQUESTED MODEL POOL`, and ranks
machines by that pool's meter rather than by whichever window reads lowest.
The human machine table appears when placement, eligibility or pool readings
decided the outcome; all candidates and relays remain available in `--json`.

`yoke session-control launch preview` and `create` accept `--level LEVEL`, or
`--surface S` with the three flags. On an item-bound `create`, `--level` also
records the level as the item's level for every stage (`--level-reason TEXT`,
default `launch-time level`); a preview or an itemless create places one launch.
`create --idempotency-key K` replays the launch already named by K. If its
session ended or was terminated, `launch_replay_finished` names that launch
and says no new worker started. Repeat create with a new key to relaunch.
A fresh item-bound create refuses `item_has_live_worker` while a live session
holds its claim or an earlier launch is pending or has a live session. The
refusal names the session and launch: wake or message that worker, or terminate
it first when a fresh worker is required; a worker holding the claim itself is
told to release it before launching its own level-change successor. Same-key
replay still deduplicates.
`--context-window` accepts a token count or compact form such as `1m`.
`--list-models --surface SURFACE` prints this machine's observed native
availability (below), plus accepted effort and context values. Claude maps context 1M to the
model's `[1m]` selector and effort to `--effort`; Codex maps effort to
`-c model_reasoning_effort=...` and refuses explicit context. Cursor passes an
exact advertised selector, such as `cursor-grok-4.6-high`; a separate matching
effort is encoded once, and a conflicting effort refuses. A base name plus
effort resolves only to an advertised variant. If a selector omits `cursor-`
and the matching prefixed selector is advertised, the refusal suggests it.
Cursor context is model-specific:
an explicit window requires that exact variant's native display label to name
it. Grok has no advertised 1M window; omit the context flag. A label establishes
a selectable option, never a served-session measurement, so unattested context
stays unknown. Preview and create use the chosen machine's native observations
for these checks. An unsupported combination is a preview refusal named for
the harness and knob, with a recovery step. A combination the
provider rejects at run time fails as `model_combo_unsupported`, retains a
bounded vendor message in launch evidence, and never retries under defaults.

## Selectable models are observed, not declared

Which models a surface will accept is a fact about the account and build on
one machine, so Yoke reads it from the surface rather than shipping a list.
Each relay poll refreshes a per-surface reading and carries it on the
heartbeat, so a model an account gains becomes visible to the fleet within
about a minute rather than within a release.

Discovery is per surface, and a surface with no adapter says so:

| Surface | Route |
|---|---|
| `cursor-cli` | `cursor-agent --list-models` |
| `codex-cli` | `codex` app-server `model/list` |
| every other surface | none declared; the reading says so by name |

Shipping one vendor's CLI adapter proves nothing about the same vendor's
desktop app or editor extension, so every known surface gets its own reading
rather than inheriting a sibling's.

Each reading names its own `status`:

| Status | Meaning |
|---|---|
| `ok` | the surface answered just now; `models` is current |
| `stale` | the last attempt failed; `models` is what it last published |
| `unsupported` | Yoke declares no listing adapter for this surface |
| `unknown` | the surface has never answered |

Only `ok` and `stale` carry models. **Neither `unknown` nor `unsupported` is
evidence that a model is unavailable** — a caller routing work reads the
status before the list. A failed probe never empties a list that was
populated: it keeps the models with their original observation time and flips
the status to `stale`, because an unreachable surface has not withdrawn
anything.

Each model entry carries what its vendor published: the selectable token, a
display description, that model's own reasoning options and default, and any
replacement target with its retirement time. Reasoning options are per model
rather than per surface — one installed app-server offers `ultra` on its
newest model and not on the one beside it.

Availability carries no dependency on researched pricing or tier data. A
model this machine can select today is reported today, whether or not
anything else is known about it.

Read it three ways:

```bash
yoke relay probe-models [--surface S] [--json]   # refresh this machine now
yoke session-control launch preview --list-models  # accepted flags beside availability
yoke steering report get                         # changed sections in held scopes
```

The relay refreshes on its own cadence during normal polling;
`yoke relay probe-models` is the bounded refresh for when you need the answer
before the next poll.

## Launched sessions run unattended

A session the launch plane starts is an autonomous worker with nobody
watching its terminal, so every launch and every wake engages the harness
permission bypass: Claude Code is launched with
`--dangerously-skip-permissions`, Codex CLI with approvals, sandbox, and hook
trust bypassed (`--dangerously-bypass-approvals-and-sandbox` plus
`--dangerously-bypass-hook-trust`; the app-server route uses equivalent
thread parameters where available), and Cursor with
`--force` alongside `--trust`. This is unconditional for launched sessions
and changes nothing about a session you start yourself.

One native gate can still refuse: Claude Code declines a bypassed background
launch until the machine has accepted the bypass disclaimer once. The launch
reports `permission_bypass_unaccepted` with the recovery step — run
`claude --dangerously-skip-permissions` interactively on that machine, accept
the prompt, then retry.

## Related

- [CLI and config](index.md)
- [Execution levels](../agents/levels.md)
