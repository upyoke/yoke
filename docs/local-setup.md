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
- Optional: a Yoke GitHub App connection for GitHub product commands.

Python is uv-provisioned, not a user prerequisite. Node.js, npm, and the
Playwright browser runtime are deferred to first `yoke qa browser` use — see
[docs/browser-substrate.md](browser-substrate.md).

### 1. Install the CLI

The public installer ensures `uv` is present, then installs `yoke` with a
single uv invocation: uv provisions a managed Python, resolves dependencies,
and links `yoke` onto PATH. It auto-launches `yoke onboard` when interactive.

```bash
curl -fsSL https://upyoke.com/install | sh
yoke --version
```

To upgrade later, rerun the same curl installer. It resolves one channel
version for every Yoke product package, selects the Yoke index ahead of an
explicit public PyPI default, and ignores ambient uv index settings for that
resolver run. Direct multi-index `uv tool install` commands are not a supported
install surface.

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
authenticates through the Yoke GitHub App once a project is bound to an installed App repository.

The repo connection is optional per project: set
`github_sync_mode=backlog_only` on a project row and its backlog stays
DB-only — every issue-sync surface skips it and no GitHub App token is resolved.
Full semantics, the flip commands, and the safe ordering for changing a
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
everywhere and the move is dump-and-restore. A self-host bundle accepts
that artifact with `yoke self-host import`:

```bash
yoke universe export --out ~/backups/
yoke universe import ~/backups/<org>-universe-<stamp>.tar
yoke self-host import ~/backups/<org>-universe-<stamp>.tar \
  --dir /path/to/yoke-server
```

Validate archives before moving or uploading them; bounded and disposable
round-trip recipes are in [Universe portability](universe-portability.md). The
artifact is one tar carrying the pg_dump custom-format payload and the freeze
receipt that binds it, so the importer verifies the file by itself. Export
uses direct DSN authority for the non-prod local universe and the authenticated
server export endpoint for a self-host HTTPS connection. Hosted connections use
Platform's coordinated dashboard download; prod-flagged Postgres connections
stay operator-only.
Local import replaces the active `local` universe after one explicit consent,
revokes imported remote credentials, and grants the machine owner local admin
authority. Local and self-host imports require an owner-only archive. Self-host
import also requires a stopped `core` and one
consent to replace the destination universe; it atomically revokes imported
tokens and browser sessions before minting one fresh org-admin token. See
[Self-Host Yoke](self-host.md) for recovery details.

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
  --api-url https://app.upyoke.com/api/orgs/upyoke \
  --token-stdin
yoke status
```

`yoke onboard` creates the machine profile, stores the env credential as an
owner-only machine secret under `~/.yoke/secrets/`, validates the active env,
and applies without printing token values. `yoke status` is the first
diagnostic to run after setup or when a project command cannot resolve context.

### 4. Optional Machine GitHub Connection

Connect a GitHub App only for GitHub product commands; backlog-only local use needs
none. Use optional **Yoke by upyoke.com** or provide a complete five-field profile.

```bash
yoke github connect
yoke github status
```

Machine authorization, App installation, and project binding are separate.
[GitHub Connection Layers](github-connections.md) explains their storage,
permissions, local overrides, and disconnect/unbind/revoke operations.

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
  --github-adoption backlog-only \
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
  --github-adoption backlog-only \
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
  --github-adoption backlog-only \
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
code delivery. `--github-adoption app-binding` requires the repository to be
present in the connected App authorization, verifies its installation and
repository ids, stores the binding, and sets `github_sync_mode=enabled`.
Use `--github-adoption backlog-only` to explicitly set `github_sync_mode=backlog_only`
until a binding is available.

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

## Detailed Setup Reference

For install-manifest contents, source-refresh previews, configuration layout,
agent-host setup, and source-development administration, see
[Local Setup Reference](local-setup-reference.md).

### Agent Hosts

See [Agent Hosts](local-setup-reference.md#agent-hosts).

## Yoke Source-Dev/Admin Setup

See [Yoke Source-Dev/Admin Setup](local-setup-reference.md#yoke-source-devadmin-setup).

## Migration and Recovery Notes

Yoke's control-plane authority is the configured env. Do not copy local DB
files into a checkout. Moving a machine means installing the product CLI,
running or restoring `yoke onboard` machine config, reconnecting secrets, and
then reinstalling each project checkout.

Database recovery is a source-dev/admin operation through the managed
Postgres backup path or an explicit server runbook, not a product setup step.
