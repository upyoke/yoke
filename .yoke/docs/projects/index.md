# Projects

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > Projects
<!-- /yoke:breadcrumbs -->

Add a project through your harness agent, then manage its capabilities,
execution guidance and shared files.

Tell the agent what already exists and where you want the checkout, for example:
“Add my existing repository at ~/work/my-app to Yoke and onboard its current
work.” The agent uses `/yoke onboard` to inspect the project, walk the decisions
with you and configure what its first work needs. For a new project, give the
agent its name, intended folder and whether it should connect to GitHub.

## Create, import, bind

Run `yoke setup` to configure your machine connection first. These commands
use the default machine config; `--config PATH` explicitly selects another.
A missing connection refuses and names the setup recovery.

From onboard or standalone:

```bash
# New repo
yoke project create ~/work/my-app \
  --slug my-app --name "My App" --github-repo owner/my-app \
  --default-branch main --public-item-prefix APP \
  --github-adoption disabled --yes

# Existing remote
yoke project import https://github.com/owner/my-app.git ~/work/my-app \
  --slug my-app --name "My App" --github-repo owner/my-app \
  --default-branch main --public-item-prefix APP \
  --github-adoption disabled --yes

# Existing local checkout
yoke onboard project ~/work/my-app \
  --slug my-app --name "My App" --github-repo owner/my-app \
  --default-branch main --public-item-prefix APP \
  --github-adoption disabled --yes
```

A project can stay local with no GitHub connection or remote:

```bash
yoke project create ~/work/local-app \
  --slug local-app --name "Local App" --default-branch main \
  --public-item-prefix APP --github-adoption disabled --yes
```

Create initializes Git; import clones the named remote; onboard adopts an
existing local checkout. Disabled GitHub adoption needs no GitHub sign-in.

## Install the operating layer

```bash
yoke project install ~/path/to/checkout
```

Writes skills, agents, hooks, contract seeds, and `.yoke/docs` from the
engine. The folder must already be a Git checkout root; initialize it with
`git init` before installing, or use project create for a new folder.
Refresh after upgrades the same way. Both operations require a
clean checkout on the project default branch, fast-forward it onto its
remote so the layer is generated against current upstream, commit the
bundle output, and push that commit. A branch that refuses a direct push
gets the same commit on a `yoke-install/<sha>` branch and a pull request;
a push that cannot land leaves `publication_pending` in the report with
the commit and the recovery command, and exits `3`.

`--force` overrides the checkout gate; `--no-commit` skips the commit;
`--no-publish` commits without pushing. A checkout with no remote, and a
default branch carrying your own unpushed commits, are both reported
rather than pushed — publishing the layer is not permission to publish
anything else on the branch.

Project uninstall also requires a clean checkout on the project's declared
default branch before removing the installed layer and committing its removal.

## Init git and a private GitHub remote

A plain folder with no `.git`, or a repo with no `origin`, uses one
registered operation — not wizard-only choreography:

```bash
yoke project git bootstrap ~/work/my-app --project my-app --yes
```

Default is dry-run. `--no-init` / `--no-create-remote` decline a step.
Existing remotes are never replaced; nested folders inside another repo
refuse. Create-new and existing-folder installers share the same local
init (starter `.gitignore` + initial commit).
If Git has no configured name or email, the initial commit fills each missing
field with a repository-local Yoke identity and reports the values used.
Existing local or global identity fields are preserved; global Git configuration
is unchanged. Setup proceeds automatically without an identity prompt.

## Onboard existing work

The `/yoke onboard` harness skill starts from what already exists: open
issues, pull requests and local session transcripts, plus anything you add.
It drafts strategy and CURRENT-PLAN, walks the decisions with you one at a
time, configures only what the first work needs, then hands off to
`/yoke steer`. Onboarding is done when that first item reaches done under its
own completion obligations. Distinct from machine `yoke setup`.

## Packs

Reusable capabilities (scaffold, deploy, runners, …) install **into the
project repo**. Yoke records the installed baseline in `.yoke/packs.json` for
update previews; project-owned customization is expected.

`yoke packs list|get|update|relink --catalog` chooses where Pack versions come
from. `served` (the default) is the release the control plane runs. Under
`yoke dev run` the default is `lane`: the Yoke source lane, so an author can
install a new Pack version before it merges. `commit:SHA` installs a version
already merged into the Yoke default branch before a release serves it,
reading a Yoke clone (`--yoke-checkout PATH`, default this yoke's own
checkout). Every report names its catalog, and `.yoke/packs.json` records each
Pack's source. A Pack installed from a lane or commit updates from the served
catalog only once a release carries that exact version; until then the update
refuses with `pack-source-unreleased` and names the `--catalog` to use.

Workbench: **Packs** and **Project settings**.

## Project settings

Project-scoped settings, capabilities, and defaults live in the workbench
**Project settings** destination (and matching CLI/capability surfaces).
Universe-wide settings live under **Universe settings**.

Retired projects are hidden from active listings and pickers. Their historical
records remain readable under the same project permissions as active projects.

## Checkout GitHub sign-in

`yoke project install ~/path/to/checkout` also converges GitHub sign-in on
both new and previously registered projects. Install and refresh select the
verified Yoke credential helper and convert the configured GitHub origin,
including SSH origins, to clean HTTPS. A same-repository explicit push URL
also becomes HTTPS. The report's `git_credentials.changes` names helper,
origin, and push URL changes; a second run reports no changes.

Run `yoke github connect` first when the report names missing machine
GitHub authorization. Other hosts and checkouts without an origin are
reported as skipped. A different push repository or unverified local helper
refuses with a reason and recovery instead of overwriting it. Source checkout
setup uses the same sign-in convergence through `yoke dev setup`.

<!-- yoke:contents -->
- [Capabilities](capabilities.md) — Inspect project providers, models and test resources.
- [Execution instructions](execution-instructions.md) — Store reusable guidance for project work and sessions.
- [Shared files](shared-files.md) — Upload files and reuse them as project context.
- [Private forks](private-forks.md) — Bind installation artifacts and maintain a private Yoke distribution.
- [Actors, members and billing](actors-members-billing.md) — Understand identity, organization access and billing ownership.
- [Hosted organization administration](hosted-org-admin.md) — Create an organization, manage invitations and approve machines.
<!-- /yoke:contents -->
