# CLI and config

## CLI

After install, `yoke` is on PATH and runs the installed product. A source-checkout
installation has its own launcher binding; changing directories does not select
a linked worktree's build. For pre-merge source development, use
`yoke dev run -- <command>` to resolve the claimed checkout and verify its
locked environment before running candidate code.

Common operators:

```bash
yoke status
yoke setup
yoke uninstall                 # full machine removal; choices and recovery: --help
yoke ui up
yoke items get PREFIX-N
yoke items get PREFIX-N body
yoke board rebuild --print-only
yoke doctor
```

Harness skills (`/yoke steer`, `/yoke idea`, …) call the same function-call
surface; CLI adapters are the operator/debug shape. Prefer
`yoke <subcommand> --help` for flags.

For one-record reads, use `yoke sessions get SESSION`, `yoke decision-requests
get REQUEST_ID`, `yoke items progress-log get PREFIX-N`, or `yoke qa artifact
get ARTIFACT_ID --requirement-id N`. The artifact `get` command returns metadata;
`yoke qa artifact read` retrieves evidence. `yoke projects environment list
--project P` lists one project's environments. `yoke qa requirement get` accepts
the id positionally or as `--requirement-id`; `yoke qa plan get` accepts an id
or project-local slug, positionally or as `--plan-id`. `yoke db read` schema
suggestions name the column storage type and label structured text columns.
`yoke items get` rejects unknown field names and prints its field catalog.
Common singular and plural guesses such as `claims work-claim`, `claims work
list`, and `qa methods` route to the registered read or claim commands. A
`say inbox` guess explains session-hook delivery and the `messages get` read.

### Model catalog revisions

The sourced model catalog lives in `model_reference_revisions` in the control
plane. `yoke models get --json` reads the revision effective now;
`--at UTC` reads the revision effective at a past or future time, and
`--revision-id REV` reads an immutable revision directly. `yoke models lookup
MODEL_ID` resolves one exact native selector or known alias against the active
catalog. Unknown research is explicit and never blocks a launch.

To refresh research, start `/yoke models`. It files a Dash for a direct
refresh, researches public primary sources, validates changed records, then
reviews a complete catalog JSON document before publication:

```bash
yoke models get --json
yoke models validate --stdin --json < changed-record.json
yoke models diff --stdin --json < candidate-catalog.json
yoke models publish --stdin --expected-base REV --source-note 'source and check date' --json < candidate-catalog.json
yoke models revisions --json
```

`diff` reports the latest revision ID, including a scheduled future revision;
start a new candidate from that revision so scheduled changes stay included.
Publication requires that exact `--expected-base` and an org admin actor. It
creates an immutable revision effective now by default; `--effective-at UTC`
schedules one for the future. A new revision cannot take effect before the
latest scheduled one. To recover, `yoke models restore REV --expected-base
CURRENT --source-note 'reason'` copies an older complete catalog into a new
revision. Research sources and check dates belong to the records, with a
publication source note for the review trail. No source edit or release is
needed for a normal refresh. Records hold facts only — prices, published
`reasoning_efforts` and `context_window_tokens`, successors. `yoke models
level-proposal` then proposes the level changes those facts imply; after
operator approval, `yoke universe levels set` stores them.

Session usage tokens remain stored in `harness_sessions.usage_totals`. Dollar
cost is derived at read time from the catalog revision effective at that
session's initial `offered_at`, and the result names the revision. Later
publications leave earlier sessions' estimates stable. Native model
availability and each model's supported reasoning levels still come from
the surface API; which model a launch uses comes from the level options.

## Execution levels

`yoke universe levels get|set` reads and replaces the universe levels, and `yoke universe level-capacity get` reads what each can launch now and why ([execution levels](reference/session-level-routing.md)).

## Machine config

`~/.yoke/config.json` holds machine-local connections and tunables: which
environment is active, API URLs, local paths. Secrets for capabilities live
under `~/.yoke/secrets/` (not in the repo).

The installer records `settings.distribution` as `{"origin": "https://api.upyoke.com",
"channel": "stable"}` using the actual install selection. `yoke update` requires
that record and uses it in a fresh shell. Select or repair it explicitly with
`yoke config distribution set --origin URL --channel NAME`; run that command's
`--help` for flags. This does not change the active control-plane connection.
Relays connected to a private API host also require this record and install
from `origin/simple/`; they do not infer an index from the API host. See
[Maintaining a private fork](private-forks.md) for artifacts and recovery.

Launch model choice does not live in machine config. A launch names a level
(`--level LEVEL`) and Yoke places it on one of that level's options — see
[launching by level](reference/session-level-routing.md#launching-by-level) —
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
yoke steering report get                         # every machine in the scope
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

## Connections

A connection is how this machine reaches a universe:

- **local-postgres** — in-process against a local DB
- **https** — relay to Cloud or self-hosted API

`yoke status` shows which connection is active.

## Workbench

```bash
yoke ui up       # open self-host workbench, or start the local view detached
yoke ui          # same as `yoke ui status` — running or stopped, plus the URL
yoke ui down     # stop it
```

On a self-host connection, `yoke ui up` opens the server's own workbench:
company sign-in opens its URL; without OIDC, the API token gets a single-use
link valid for two minutes. Rerun to replace an expired link. On Local
(typically `http://127.0.0.1:8688`), it starts a machine daemon: closing the
terminal leaves it serving; macOS brings it back after reboot until `ui down`.

The view serves a database this machine holds — a non-prod local-postgres
connection — and names the environment that answered in the page footer.
Point it at a particular one by naming that env on the command:

```bash
YOKE_ENV=local-dev yoke ui up   # serve that universe; the daemon keeps the env
yoke env list                   # the connections this machine has
```

That is the recipe to use when rendering a view for review: the footer
label travels into a screenshot, so the capture says which universe
produced it. Any connection the server would answer from somewhere else
refuses at startup and names the env to switch to.

The URL carries a session token — treat it like a password. The token is
stable per machine, so the URL you bookmark keeps working across up/down
cycles. The server binds loopback only and refuses remote-facing hosts.

## Project-local `.yoke/`

Installed into each managed repo: skills, agent adapters, hooks, policy,
and `.yoke/docs` (this public corpus). Board markdown under `.yoke/BOARD.md`
is a generated view — do not hand-edit it as source of truth.
