# Onboarding an External Project

This is the product path for operating a project repo from a machine that does
not have a Yoke source checkout. The flow has two layers:

1. **Machine onboarding:** install the product CLI, connect the machine to a
   Yoke env, and optionally connect machine GitHub access.
2. **Project onboarding:** create, import, or register a project, install the
   project-local operating layer, create the durable checklist, then hand the
   repo to `/yoke onboard-project`.

Source-dev/admin and server-only leftovers are named at the end.

## 1. Install the Product CLI

The only prerequisites are a shell, `curl`, and `uv`. The public installer
ensures `uv` is present (installing it on consent when missing), then installs
`yoke` with a single uv invocation: uv provisions a managed Python, resolves
dependencies, and links `yoke` onto PATH. The installer auto-launches
`yoke onboard` when interactive.

```bash
curl -fsSL https://upyoke.com/install | sh
yoke --version
```

The manual, advanced equivalent of the install step is a direct uv invocation
using one resolved channel version for every Yoke product package. To upgrade
later, rerun the curl installer or rerun the same lockstep uv command with the
new channel version:

```bash
uv tool install yoke-cli==<version> --python '>=3.10' --reinstall --with yoke-contracts==<version> --with yoke-harness==<version> --with yoke-core==<version> --index-url https://api.upyoke.com/simple/ --extra-index-url https://pypi.org/simple/
```

`git` is needed only at the project step below, and only for create, clone,
import, or local-checkout modes.

## 2. Onboard the Machine

`yoke onboard` is a full-screen wizard — Install/PATH, Account, GitHub,
Project, Review — driven by the arrow keys, redrawing in place. The Account
step opens on a deployment-destination picker: where should this Yoke live —
this machine (the free local universe, no account), a team server (your own
URL plus a token), or upyoke.com (hosted sign-in). Only the sign-in lane
changes with the answer; every other step is destination-independent, and
the wizard previews every persistent write before applying. Re-running
onboarding ADDS a connection for the newly picked destination — a
connection for another destination stays in place, and `active_env` follows
the flow that just completed.

```bash
yoke onboard
yoke status
```

Silent, non-interactive apply with `--yes`. The destination flags mirror the
picker: `--local` creates/verifies the machine-local universe (no token, no
API URL), `--connect URL` targets a team server or hosted endpoint, and the
`YOKE_ONBOARD_DESTINATION` environment value (`local`, `hosted`, or a server
URL) routes the same way for flagless automation. The sign-in example below
connects to the hosted platform's prod env; a self-hosted deployment passes
its own `--api-url` (or `--connect URL`) instead — the machine-config
connection entry it writes is the API authority either way:

```bash
yoke onboard --local --non-interactive --yes   # machine-local universe

yoke onboard --yes \
  --config ~/.yoke/config.json \
  --env prod \
  --api-url https://api.upyoke.com/v1 \
  --token-stdin
yoke status
```

`yoke onboard` writes the machine config, stores the env credential in
`~/.yoke/secrets/`, validates the env, and applies without leaking secret
values.

Optional machine GitHub connection:

```bash
yoke github connect
yoke github status
```

`yoke github connect` opens GitHub's device-authorization flow. Yoke stores an
owner-only refresh credential reference, then lists the App installations and
repositories the signed-in user can reach. A project binding is created only
after onboarding selects one of those repositories; a typed repository id and
installation id are verified again by the server before the binding is saved.

## 3. Choose the Project Entry Path

The `yoke onboard` wizard's Project step covers every entry mode
interactively. The standalone commands below run a single mode
non-interactively when you want to script one path.

### New repo

```bash
yoke project create ~/work/demo \
  --slug demo \
  --name "Demo" \
  --github-repo owner/demo \
  --default-branch main \
  --public-item-prefix DMO \
  --github-adoption app-binding \
  --config ~/.yoke/config.json \
  --yes
```

This initializes the checkout, creates the project, records the GitHub App repo
binding when requested, registers the checkout, and runs project install.

### Existing remote

```bash
yoke project import git@github.com:owner/demo.git ~/work/demo \
  --slug demo \
  --name "Demo" \
  --github-repo owner/demo \
  --default-branch main \
  --public-item-prefix DMO \
  --github-adoption backlog-only \
  --config ~/.yoke/config.json \
  --yes
```

This clones the remote, creates or imports the project identity, registers the
checkout, and runs project install.

### Existing local checkout

Preview first:

```bash
yoke onboard project ~/work/demo \
  --slug demo \
  --name "Demo" \
  --github-repo owner/demo \
  --default-branch main \
  --public-item-prefix DMO \
  --github-adoption app-binding \
  --config ~/.yoke/config.json \
  --dry-run \
  --json
```

Apply after reviewing the preview:

```bash
yoke onboard project ~/work/demo \
  --slug demo \
  --name "Demo" \
  --github-repo owner/demo \
  --default-branch main \
  --public-item-prefix DMO \
  --github-adoption app-binding \
  --config ~/.yoke/config.json \
  --yes \
  --json
```

### Existing server-side project

If an admin already provisioned the project row and capabilities, install only
the local operating layer:

```bash
yoke project install ~/work/demo \
  --project-id <project-id> \
  --config ~/.yoke/config.json
```

## 4. Make the GitHub Adoption Choice Explicit

Project onboarding requires an explicit choice before applying GitHub
automation when `--github-repo` is present:

- `app-binding` verifies and records a GitHub App installation/repository
  binding and sets `github_sync_mode=enabled`.
- `backlog-only` explicitly sets `github_sync_mode=backlog_only`.

Dry-run JSON includes `github_adoption` and `automation_preview`. The preview
names the project write surface and the GitHub categories Yoke is preparing
to manage: labels, issue templates, pull request templates, Actions variables,
Actions secrets, branch protection, and environment protection.

Project onboarding accepts no project-supplied GitHub credential. GitHub
automation uses GitHub App repo bindings; a backlog-only project does not
resolve GitHub auth at all. `aws-admin` capability secrets and
`ssh.private_key` are machine-local files under
`~/.yoke/secrets/capability-secrets/<project>/<capability>/`. Raw secret
values are not printed.

The default App grant is least-privilege: Metadata read; Checks read; and
Issues, Pull requests, Contents, Actions, Workflows, Secrets, and Variables
write. Repository creation, GitHub environment configuration, branch
protection, and runner administration require the optional Administration
permission. Without it, Yoke opens or names the corresponding GitHub settings
page and continues without claiming that the administrative step ran.

## 5. Capture the Install Report

Keep the JSON output from the applied project command. It is the install
report consumed by `/yoke onboard-project`.

The report identifies:

- project id, slug, GitHub repo, default branch, and item prefix
- checkout path and machine-config registration
- project install operation and bundle source
- files written, pruned, or preserved
- seeded contract files and DB-rendered strategy files
- hook changes and warnings
- GitHub adoption choice and preview

## 6. Initialize the Durable Checklist

Create the checklist after project install:

```bash
yoke onboard checklist init \
  --config ~/.yoke/config.json \
  --checkout ~/work/demo \
  --project-id <project-id> \
  --json
```

The command returns a `run_id` and writes the rendered checklist view under
the project-local `.yoke/onboarding/` directory when the env provides one.
The authoritative read is always:

```bash
yoke onboard checklist --run-id <run-id> --json
```

## 7. Hand Off to the Harness

Open the installed project checkout in a supported harness and run:

```text
/yoke onboard-project --project-root ~/work/demo --run-id <run-id>
```

Pass the captured install report when prompted, or include its path:

```text
/yoke onboard-project --project-root ~/work/demo \
  --run-id <run-id> --install-report /path/to/install-report.json
```

The slash-command skill consumes the install report and durable checklist. It
does not rediscover deterministic setup by crawling the repo. It updates
checklist rows as it surveys the repo, asks only for missing human context,
configures strategy/project-structure/capabilities/delivery through sanctioned
Yoke surfaces, and records verification evidence.

## 8. Verify the Installed Project

Useful product-level checks from the project checkout:

```bash
yoke status --repo-root ~/work/demo
yoke projects checkout-context
yoke onboard checklist --run-id <run-id> --json
yoke board rebuild --force
```

Then make a normal project commit. The installed hook shims run through the
`yoke` launcher; older checkout-only hook commands should be refreshed with:

```bash
yoke project refresh ~/work/demo --config ~/.yoke/config.json
```

## What Project Install Writes

`yoke project install` fetches the active env's install bundle and writes:

- `.claude/skills/yoke/` and `.codex/skills/yoke/`
- `.claude/agents/` and `.codex/agents/`
- `.claude/settings.json` and `.codex/hooks.json` hook entries
- git hook shims
- `.yoke/install-manifest.json`
- seed-if-missing `.yoke/` contract files
- DB-rendered `.yoke/strategy/` views

Install never writes credentials into the repo. Edited project contract files
are preserved on refresh. Strategy files are DB-rendered views and survive
uninstall. Generated board views remain generated output.

## Source-Dev/Admin and Server-Only Leftovers

These are not external-project onboarding steps:

- Building or distributing release artifacts with
  `uv run python -m yoke_core.tools.build_release`.
- Minting actor tokens and granting env roles.
- Server-side project row repair when product create/import/onboard cannot be
  used.
- Capability repair beyond product onboarding, including deployment provider
  credentials.
- Deployment flow authoring and server runtime provisioning.
- Postgres backup/restore, migration applies, or direct DB diagnostics.
- Yoke source checkout setup, install-bundle authoring, and packet rendering.

Those sit beyond the **source-dev/admin boundary** — the Yoke
source-dev/admin lane in `docs/local-setup.md#yoke-source-devadmin-setup`.
