# Local Setup

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

Yoke has two local setup lanes:

- **Product/operator setup** is the normal path. Install the CLI as an app,
  onboard the machine, install a project, then hand the project to
  `/yoke onboard-project`.
- **Yoke source-dev/admin setup** is only for people editing Yoke itself
  or operating the server side. It starts with the product path, then adds
  `yoke dev setup`.

Running the Yoke API server on your own hardware is its own lane — the
`yoke self-host init` compose bundle, documented in
[docs/self-host.md](self-host.md).

## Product/Operator Setup

This path does not require a Yoke source checkout.

### Prerequisites

The install-time prerequisite set is just a shell, `curl`, and `uv` (installed
on consent when missing). Everything else is deferred until it is needed:

- A Yoke actor token for the target env.
- `git`: needed only at the `yoke onboard` project step, and only for a
  create, clone, import, or local-checkout mode. Machine-only onboarding needs
  no git.
- Optional: a Yoke GitHub App connection if this machine should run GitHub
  product commands.

Python is uv-provisioned, not a user prerequisite. Node.js, npm, and the
Playwright browser runtime are deferred to first `yoke qa browser` use — see
[docs/browser-substrate.md](browser-substrate.md).

### 1. Install the CLI

The public installer ensures `uv` is present, then installs `yoke` with a
single uv invocation: uv provisions a managed Python, resolves dependencies,
and links `yoke` onto PATH. It auto-launches `yoke onboard` when interactive.

```bash
curl -fsSL https://api.upyoke.com/install | bash
yoke --version
```

The manual, advanced equivalent of the install step is a direct uv invocation
using one resolved channel version for every Yoke product package. To upgrade
later, rerun the curl installer or rerun the same lockstep uv command with the
new channel version:

```bash
uv tool install yoke-cli==<version> --python '>=3.10' --reinstall --with yoke-contracts==<version> --with yoke-harness==<version> --with yoke-core==<version> --index-url https://api.upyoke.com/simple/ --extra-index-url https://pypi.org/simple/
```

### 2. Local Mode: Create a Machine-Local Universe (free, no signup)

Local mode runs the whole engine on your machine: one embedded Postgres
under `~/.yoke/local-universe/` carrying the same control-plane schema as
every other deployment mode. No account, no token, no server — the DSN
never leaves the machine, and the engine stores no human credentials
(local mode has one auto-created human actor and no user records).

```bash
yoke init --local --org-name "My Org"
yoke status
```

`yoke init --local` fetches per-platform Postgres binaries on first run
(into `~/.yoke/postgres/<version>/`), starts the embedded server
(unix-socket-only, trust auth on the private socket), bootstraps the full
control-plane schema, ensures the org identity card and the one human
actor, then records a `local` connection in `~/.yoke/config.json` and
sets it as the machine default. Re-running detects the live universe and
reports; a conflicting existing `local` connection is only replaced with
`--force`.

GitHub sync needs no server in any mode: sync executes wherever the
engine dispatches. In local mode the engine dispatches in-process and
authenticates through the Yoke GitHub App once a project is bound to an
installed App repository.

The repo connection is optional per project: set
`github_sync_mode=backlog_only` on a project row and its backlog stays
DB-only — every issue-sync surface skips it and no GitHub App token is
resolved. Full semantics, the flip commands, and the safe ordering for changing a
project's `github_repo` live in [github-sync.md](github-sync.md).

Manage the embedded server directly when needed:

```bash
yoke local-postgres status
yoke local-postgres start
yoke local-postgres stop
```

Your universe is portable. `yoke universe export` dumps the whole
database to one self-contained artifact — the leave/graduate half of
moving a universe between deployment modes, since one schema runs
everywhere and the move is dump-and-restore (the restore/upload half
into a hosted or self-hosted deployment arrives with that platform
surface):

```bash
yoke universe export                 # <org>-universe-<utc-ts>.dump in the cwd
yoke universe export --out ~/backups/
```

The artifact is a pg_dump custom-format archive (compressed,
`pg_restore --list`-able). Export requires holding the database DSN, so
it is sanctioned for the non-prod local universe: an https (hosted or
self-hosted) connection refuses with guidance, and prod-flagged Postgres
connections stay operator-only.

The `yoke onboard` wizard below drives the same birth machinery when its
deployment-destination picker answers "This machine" (or with `--local` /
`YOKE_ONBOARD_DESTINATION=local` non-interactively), so either entry point
lands the identical `local` connection. Connected setups (hosted or
self-hosted env with a token) pick a sign-in destination in the same wizard;
all destinations can coexist on one machine as separate `connections`
entries selected via `yoke env use` or `--env`.

### 3. Onboard the Machine

`yoke onboard` is a full-screen wizard. A fixed header and stepper stay on
screen — Install/PATH, Account, GitHub, Project, Review — while the body
changes; you move through it with the arrow keys, redrawing in place. The
Account step opens on the deployment-destination picker (this machine / a
team server / upyoke.com); only the sign-in lane changes with the answer —
"This machine" replaces sign-in with the local-universe setup above, a team
server collects your server URL then a token, upyoke.com signs in to the
hosted platform. Before any mutation it previews a write plan (machine,
control-plane, repo-local, source-dev/admin writes), then applies on a
single confirm. Re-running adds the newly picked destination's connection
beside any existing ones; `active_env` follows the flow that completed.

```bash
yoke onboard
yoke status
```

Silent, non-interactive apply with `--yes`. `--local` and `--connect URL`
mirror the picker without the TUI; the sign-in example connects to the
hosted platform's prod env, and a self-hosted deployment passes its own
`--api-url` (or `--connect URL`) instead — the machine-config connection
entry it writes is the API authority either way:

```bash
yoke onboard --local --non-interactive --yes   # machine-local universe

yoke onboard --yes \
  --config ~/.yoke/config.json \
  --env prod \
  --api-url https://api.upyoke.com/v1 \
  --token-stdin
yoke status
```

`yoke onboard` creates the machine profile, stores the env credential as an
owner-only machine secret under `~/.yoke/secrets/`, validates the active env,
and applies without printing token values. `yoke status` is the first
diagnostic to run after setup or when a project command cannot resolve context.

### 4. Optional Machine GitHub Connection

Connect the Yoke GitHub App only when this machine should run GitHub product
commands such as repository checks or product onboarding previews.

```bash
yoke github connect
yoke github status
```

The machine connection records GitHub App authorization metadata.
Project runtime authority comes from a project repository binding to an
installed App repository.

### 5. Set Up a Project

The `yoke onboard` wizard's Project step is the primary way to pick a project
source (machine-only, create, clone, import, local checkout, or source-dev/admin
opt-in). The standalone commands below script a single mode non-interactively.

New repository:

```bash
yoke project create ~/work/my-app \
  --slug my-app \
  --name "My App" \
  --github-repo owner/my-app \
  --default-branch main \
  --public-item-prefix APP \
  --github-adoption skip \
  --config ~/.yoke/config.json \
  --yes
```

Existing remote:

```bash
yoke project import git@github.com:owner/my-app.git ~/work/my-app \
  --slug my-app \
  --name "My App" \
  --github-repo owner/my-app \
  --default-branch main \
  --public-item-prefix APP \
  --github-adoption skip \
  --config ~/.yoke/config.json \
  --yes
```

Existing local checkout:

```bash
yoke onboard project ~/work/my-app \
  --slug my-app \
  --name "My App" \
  --github-repo owner/my-app \
  --default-branch main \
  --public-item-prefix APP \
  --github-adoption skip \
  --config ~/.yoke/config.json \
  --dry-run \
  --json
```

After reviewing the dry-run preview, rerun with `--yes` to apply.

Pre-provisioned project that only needs the local operating layer:

```bash
yoke project install ~/work/my-app \
  --project-id <project-id> \
  --config ~/.yoke/config.json
```

`yoke project create`, `yoke project import`, and `yoke onboard project`
all finish by registering the checkout in machine config and running
`yoke project install`. `yoke project install` can also be run directly
when the project already exists in the active env.

### 6. Project GitHub Adoption Choices

When `--github-repo` is present, Yoke records the repository identity for
code delivery. GitHub issue automation is enabled by binding the project to
an installed Yoke GitHub App repository; use `--github-adoption skip` for
backlog-only setup until that binding is available.

Dry runs and JSON output include an `automation_preview` covering project
writes plus GitHub labels, issue templates, pull request templates, Actions
variables, Actions secrets, branch protection, and environment protection.
GitHub App credentials are never printed.

### 7. Install Report, Checklist, and Handoff

Keep the JSON output from the project command as the install report. It records
the project id, checkout registration, install mode, files written or
preserved, strategy files, contract files, hook changes, and warnings.

Initialize the durable onboarding checklist:

```bash
yoke onboard checklist init \
  --config ~/.yoke/config.json \
  --checkout ~/work/my-app \
  --project-id <project-id> \
  --json
```

The checklist is the handoff contract between deterministic product setup and
agentic project adoption. Open the installed project in a supported harness and
run:

```text
/yoke onboard-project --project-root ~/work/my-app --run-id <run-id>
```

Pass the captured install report when the harness asks for it, or include the
report path in the slash-command arguments when available.

### What Project Install Writes

`yoke project install` fetches the active env's install bundle and writes the
project-local operating layer:

- Yoke skills under `.claude/skills/yoke/` and `.codex/skills/yoke/`.
- Rendered agent adapters under `.claude/agents/` and `.codex/agents/`.
- Hook entries merged into `.claude/settings.json` and `.codex/hooks.json`.
- Git hook shims for the installed guardrails.
- `.yoke/install-manifest.json` for refresh and uninstall tracking.
- Seed-if-missing project contract files under `.yoke/`.
- DB-rendered strategy views under `.yoke/strategy/`.

Refresh and uninstall are manifest-tracked:

```bash
yoke project refresh ~/work/my-app --config ~/.yoke/config.json
yoke project uninstall ~/work/my-app --config ~/.yoke/config.json
```

Project-owned contract files are preserved once edited. Generated board views,
credentials, runtime directories, and machine config are not installed into the
repo by the project bundle.

## Configuration Model

Machine-local runtime context lives in `~/.yoke/config.json`. It owns the
active env, credential source, temp/cache roots, checkout-to-project
bindings, board render path, and physical worktree layout.

Project-local configuration lives in the project checkout:

- `.yoke/board.json` controls board rendering appearance and behavior.
- `.yoke/board-art` contains board presentation variants.
- `.yoke/lint-config` and `.yoke/labels` carry guardrail and label policy.
- `.yoke/runbooks/` is project-owned onboarding context; `.yoke/strategy/`
  holds untracked rendered views of the DB-authoritative strategy docs.

Shared project behavior lives in the Yoke DB, not checkout files:

- `project-policy` capability settings own `base_branch`, `wip_cap`,
  `default_priority`, `merge_conflict_threshold`, `max_attempts`, and
  `file_line_limit`.
- `session-routing` capability settings own default lanes, lane path
  allowlists, and `/yoke do` process-offer policy.

Generated views such as `.yoke/BOARD.md` are read-only output. Regenerate
them through Yoke commands; do not edit them directly.

Inspect the current machine and project binding with:

```bash
yoke status
yoke projects checkout-context
```

## Local Core Product Launcher

Machines that need a self-hosted local Yoke API use the product `yoke core`
launcher. This is the explicit source-dev/admin local-core path; it does not
grant normal operators direct DB authority, and it does not pull a public
default core image.

```bash
yoke core build --checkout /path/to/yoke --dry-run
yoke core start --from-checkout /path/to/yoke --build
yoke core status --json
yoke core logs
yoke core stop
yoke core upgrade --from-checkout /path/to/yoke --build --dry-run
```

State lives under `~/.yoke/local-core`. Start with a dry run when Docker,
Colima, or local runtime state is uncertain. Use `--image IMAGE` only when an
already-built local/private Yoke core image should be run directly.

## Agent Hosts

Yoke runs inside supported harnesses through installed project skills and
hooks.

- **Claude adapter:** open the installed project checkout and use `/yoke ...`
  slash commands.
- **Codex adapter:** open the installed project checkout; Codex reads the
  installed `.codex/` skills and hooks.

First project adoption after install should start with:

```text
/yoke onboard-project --project-root <checkout> --run-id <run-id>
```

After adoption, normal item flow is:

```text
/yoke idea "my first item"
/yoke advance YOK-N implementing
/yoke usher YOK-N
```

## Yoke Source-Dev/Admin Setup

Use this lane only when you are editing Yoke itself, maintaining install
bundles, running server-side provisioning, or developing the CLI/core.

Start with the product setup above, then install the Yoke source checkout as
a normal project:

```bash
git clone git@github.com:upyoke/yoke.git ~/yoke
yoke project install ~/yoke \
  --project-id <yoke-project-id> \
  --config ~/.yoke/config.json
```

Then run the explicit source-dev setup:

```bash
yoke dev setup ~/yoke \
  --config ~/.yoke/config.json \
  --set-active-env
```

Useful source-dev flags include `--editable-install`, `--with-test-postgres`,
and the tunnel or authority flags shown by `yoke dev setup --help`.

`--editable-install` runs `pip install -e` for the four packages and then
replaces pip's absolute-path editable artifacts with a config-driven shim
(`_yoke_editable.pth` + `_yoke_editable_loader.py` in site-packages). The shim
resolves the checkout root at each interpreter start from `YOKE_REPO_ROOT`, then
machine config (`~/.yoke/config.json`), then an install-time fallback — so moving
or renaming the checkout only needs the machine-config path updated, with no
reinstall. A bare `pip install -e` (without `yoke dev setup`) still bakes the
absolute path and must be rerun after a move.

`yoke status` states which binding is live on its `install:` line —
`packaged wheel <version>` or `source checkout <path>`. The binding only
changes through this explicit setup; a checkout's presence on disk activates
nothing.

Source-dev/admin-only work includes:

- Building or publishing release artifacts with
  `uv run python -m yoke_core.tools.build_release`.
- Updating install bundles and rendered agent packets.
- Minting actor tokens and granting roles for a deployed env.
- Creating or repairing server-side project rows, capabilities, and deployment
  flows when product `project create/import/onboard` cannot reach the target
  env.
- Running migrations, Postgres backup/restore, or direct DB diagnostics.
- Recovering stale sessions or other server-side state.

Do not teach these as normal project setup. Normal operators use
`yoke onboard`, `yoke status`, project create/import/onboard/install, and
the durable checklist handoff.

## Migration and Recovery Notes

Yoke's control-plane authority is the configured env. Do not copy local DB
files into a checkout. Moving a machine means installing the product CLI,
running or restoring `yoke onboard` machine config, reconnecting secrets, and
then reinstalling each project checkout.

Database recovery is a source-dev/admin operation through the managed
Postgres backup path or an explicit server runbook, not a product setup step.
