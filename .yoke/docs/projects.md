# Projects

## Create, import, bind

From onboard or standalone:

```bash
# New repo
yoke project create ~/work/my-app \
  --slug my-app --name "My App" --github-repo owner/my-app \
  --default-branch main --public-item-prefix APP \
  --github-adoption disabled --yes

# Existing remote
yoke project import git@github.com:owner/my-app.git ~/work/my-app \
  --slug my-app --name "My App" --github-repo owner/my-app \
  --default-branch main --public-item-prefix APP \
  --github-adoption disabled --yes

# Existing local checkout
yoke onboard project ~/work/my-app \
  --slug my-app --name "My App" --github-repo owner/my-app \
  --default-branch main --public-item-prefix APP \
  --github-adoption disabled --yes
```

## Install the operating layer

```bash
yoke project install ~/path/to/checkout
```

Writes skills, agents, hooks, contract seeds, and `.yoke/docs` from the
engine. Refresh after upgrades the same way. Both operations require a
clean checkout on the project default branch, then commit the bundle
output. `--force` overrides the checkout gate; `--no-commit` skips the
commit. Pushing stays an operator decision.

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

## Execution-ready onboard

The `/yoke onboard` harness skill makes a wired project execution-ready:
strategy docs, execution profile, Packs, hosting, environments, gated first
deploy, seeded work. Distinct from machine `yoke onboard`.

## Packs

Reusable capabilities (scaffold, deploy, runners, …) install **into the
project repo**. Yoke records the installed baseline in `.yoke/packs.json` for
update previews; project-owned customization is expected.

Workbench: **Packs** and **Project settings**.

## Project settings

Project-scoped settings, capabilities, and defaults live in the workbench
**Project settings** destination (and matching CLI/capability surfaces).
Universe-wide settings live under **Universe settings**.
