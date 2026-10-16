# CLI and config

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > CLI and config
<!-- /yoke:breadcrumbs -->

Read command help, select connections and open the workbench from your machine.

## CLI

Read help from the command catalog down to the operation before running it:

```bash
yoke --help
yoke project --help
yoke project create --help
```

Choose the category from root help, then the command from category help; use
that command’s help for its arguments and flags. [Help and replies](help.md)
owns the help-reading and output contract.

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

Session usage tokens remain stored in `harness_sessions.usage_totals`; its
observation clock uses fixed-six UTC or null. Dollar
cost is derived at read time from the catalog revision effective at that
session's initial `offered_at`, and the result names the revision. Later
publications leave earlier sessions' estimates stable. Native model
availability and each model's supported reasoning levels still come from
the surface API; which model a launch uses comes from the level options.

## Execution levels

`yoke universe levels get|set` reads and replaces the universe levels, and `yoke universe level-capacity get` reads what each can launch now and why ([execution levels](../agents/levels.md)).

## Connections

A connection is how this machine reaches a universe:

- **local-postgres** — in-process against a local DB
- **https** — relay to Cloud or self-hosted API

`yoke status` shows which connection is active.

## Workbench

```bash
yoke ui up       # open self-host workbench, or start the local view detached
yoke ui          # same as `yoke ui status` — running or stopped, without sign-in tokens
yoke ui down     # stop it
```

On a self-host connection, `yoke ui up` opens the server's own workbench:
company sign-in opens its URL; without OIDC, the API token gets a single-use
link valid for two minutes. Rerun to replace an expired link. On Local
(typically `http://127.0.0.1:8688`), it starts a machine daemon: closing the
terminal leaves it serving; macOS brings it back after reboot until `ui down`.
Sign-in links go straight to the browser and never appear in text or JSON.
Agents, headless callers and `--no-browser` get a named browser reason: run
`yoke ui up` from your own terminal on a machine with a display to sign in.

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

Project-scoped commands use your registered checkout or explicit project
selection. Outside a project, a missing selection returns `project_required`
and lists only projects you can access; permission, ambiguity and gate
refusals retain their actual reasons. Board rebuild requires a registered
checkout, even when only one is registered; pass `--repo-root PATH` from
elsewhere. Doctor's last report uses your checkout or `--project P`.
An unmapped folder is a `project_mapping_missing` warning in status.

## Related

- [Machine config and native models](machine-config.md)

<!-- yoke:contents -->
- [Machine config and native models](machine-config.md) — Select configuration and inspect native model availability and unattended launches.
- [Help and replies](help.md) — Read focused command help and choose human or machine output.
- [HTTPS connection diagnostics](https-connection-diagnostics.md) — Diagnose API transport and connection failures.
- [Machine authorization](machine-authorization.md) — Connect a machine and inspect actor approval and hosted handoff.
<!-- /yoke:contents -->
