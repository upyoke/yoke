# A01 — Alex, solo, idea-only, macOS, no remote, no deploy

**Vector:** solo · idea-only · hosting none · macOS · no remote · deploy none.

Alex has a product idea, no repo yet, a MacBook, and does not want a cloud
account. Goal: get Yoke locally and start capturing work.

## Fit / break / gaps

| | |
|---|---|
| Fits | Local destination ("This machine", free, no account). Create-new project with no GitHub. Hosting skip. Seed work without a live deploy. |
| Breaks | Installer hand-off names Claude Code or Codex, not Cursor. Execution profile still proposes stage+prod and a default deploy flow. |
| Gaps | No "this project does not deploy" declaration. Idea intake will stamp the project default flow onto every item. |

## Transcript — public installer

Command: `curl -fsSL https://upyoke.com/install | sh`

OS check in the shim: `Darwin|Linux` — macOS passes.

If `uv` is missing (Homebrew on PATH — typical Mac):

```
[branded figlet welcome]
☀  Your operating system for software delivery

☀ Yoke's only prerequisite — uv/uvx — isn't installed yet.
☀ Install it with Homebrew?  brew install uv  [Y/n]
  (no Homebrew? falls back to the official uv installer)
```

**User:** Enter (default Yes).

Shim runs `brew install uv` (Astral installer if brew fails), then
`uv run --isolated --no-project python` on the downloaded `install.py`.

```
☀ Setting up Yoke…
☀ Yoke v{channel version} is ready
☀ Starting Yoke onboard…
```

The shim launches `yoke onboard --post-install` with no extra consent.

## Transcript — `yoke onboard` wizard

### Install / PATH (`onboard_wizard_path.py`)

```
{brand} {version} is installed.
Congrats! You're on your way to an eternity of Yoke.
  Continue
  Quit
```

**User:** Continue.

If PATH needs a fix:

```
Add {brand} to your PATH.
Yoke lives in {tool_bin_dir} (your zsh shell).
This shell sees: …
A new Terminal login shell sees: …
  Add yoke to my PATH     (updates your shell startup file)
  See exactly what changes
  Skip
```

**User:** Add yoke to my PATH.

Then verified continue: "choose where your Yoke lives".

### Account (`DESTINATION_ROWS`)

```
Where should this Yoke live?
Every home runs the full engine — you can add another later.
  This machine          free · no account · stays here
  A team server         the URL of your team's self-hosted Yoke server
  upyoke.com            hosted by Yoke · private beta
  stage.upyoke.com      staging environment · for testing
```

**User:** This machine.

```
Your Yoke lives on this machine.
Free, no account — everything stays on this computer.
  • Apply creates a private local universe under ~/.yoke
    (embedded Postgres, the full Yoke schema).
  Continue
```

**User:** Continue.

### GitHub (`MACHINE_GITHUB_TITLE`)

```
Connect GitHub?
Use the Yoke GitHub App to authorize this machine for local repo
operations, or stay disabled.
  Connect GitHub     open the Yoke GitHub App flow
  Skip GitHub        connect later
```

**User:** Skip GitHub. (no remote)

### Project (`MODE_ROWS`)

```
Set up a project.
Where's the code? You can change this later.
  Existing folder on my machine     git repo or not
  Clone a project from GitHub       into a new folder
  Create a new project              new folder, optionally also created on GitHub
  Develop Yoke itself               advanced · contributors
  Don't set up a project now        just the machine
```

**User:** Create a new project.

```
Name your new project folder.
Where should Yoke create it? It makes the folder and a git repo.
  ~/code/my-project
```

**User:** `~/code/notebook-app`

```
Name your project.
Short ID — lowercase and hyphens (e.g. my-project).
```

**User:** `notebook-app` (suggested from folder via `slug_from_checkout`)

```
Give it a friendly name.
The display name people read — anything you like.
```

**User:** `Notebook App`

```
Also publish to GitHub?
Yoke creates the repo with GitHub authorization and connects it as your remote.
  Yes — publish to GitHub     create + connect the repo
  No — keep it local          you can publish later
```

**User:** No — keep it local.

```
Pick the default branch.
Yoke fills this in for you — change it if you like.
```

Placeholder: `main` (`DEFAULT_NEW_REPO_BRANCH`).

**User:** Enter (`main`).

```
Pick the issue ID prefix.
The PROJ in PROJ-123 — Yoke suggests one from your project name.
```

Suggested: `NOTE` (`prefix_from_slug("notebook-app")`).

**User:** `NOTE`

### Board art

```
Give your board a face.
Every project gets a live status board — a progress map that fills
in as work moves, topped with headers you design.
  Let's design it     a progress map + at least one header
```

**User:** Let's design it. Accepts the map spelling, picks ASCII, continues
with one header.

### Hosting

```
Connect your hosting provider?
AWS for now. One click creates the deploy credential; paste its two
values below.
  Save & verify     redacted caller-identity check
  Skip for now      connect later via /yoke onboard or re-run
```

**User:** Skip for now. (no AWS, no hosting)

### Review

```
Review what Yoke will save.
Nothing is written until you choose Apply.
  Apply      writes everything above
  Cancel     nothing is saved
```

**User:** Apply.

Apply creates the local universe, writes machine config, creates
`~/code/notebook-app` as a git repo on `main`, registers project
`notebook-app` with prefix `NOTE`, GitHub adoption disabled.

### Installer hand-off (after wizard)

```
☀ Yoke installation complete.

  ▌ Next: make it execution-ready.
  ▌  1  source "~/.zprofile"
  ▌     (this terminal only; new windows already have it)
  ▌  2  open Claude Code or Codex in your project folder
  ▌  3  run /yoke onboard
```

**User** opens Cursor in `~/code/notebook-app` anyway (not named) and runs
`/yoke onboard`.

## Transcript — `/yoke onboard` skill

Init: `yoke onboard checklist init --project notebook-app --checkout ~/code/notebook-app --json`

1. Strategy: `yoke strategy seed-defaults`, then drafts MISSION / VISION /
   MASTER-PLAN / LANDSCAPE / CURRENT-PLAN. Agent asks only what the empty
   repo cannot answer. Writes via `yoke strategy doc replace`.
2. Profile confirmation (stop 1 of 2). Proposal from
   `profile-and-scaffold.md`: scaffold Pack `webapp-scaffold`; infra Packs
   `pulumi-foundation` · `vps-hosting` · `webapp-environment-infrastructure`;
   deploy Packs `registry-oidc` · `production-deploy`; capability `aws-admin`;
   **environments stage + prod**; default subdomain.
3. **User** should adjust: drop hosting Packs and `aws-admin`; keep local
   scaffold or skip it (idea-only). If they rubber-stamp the proposal, the
   profile creates a deploy default they do not have.
4. Hosting step: skip probe fails (no `aws-admin`). Operator defers:
   `hosting-setup=deferred`. Step 7 unreachable. Step 8 still runs.
5. Seed: `yoke project-structure deploy-defaults get --project notebook-app`.
   Empty → omit `--deployment-flow` on `yoke items create`. Non-empty → every
   seeded issue gets the default flow.

## Crux

| Requirement | Where it should be declared | Refusal when absent | Instead |
|---|---|---|---|
| Deployment / environment | Execution-profile confirmation: hosting and env are optional; default flow may be merge-only (`target_tier` NULL) or unset | Usher Route A / omit `--deployment-flow`; never stamp a persistent flow | Local merge, no pipeline |
| GitHub merge target | Already optional (Skip GitHub / keep local) | GitHub automation disabled until App sees the repo | Local default branch `main` |
| Migration | Not asked; N/A for empty repo | — | No `migration_model` |

Ledger: G-no-deploy-default-flow, G-execution-profile-no-hosting-still-envs, G-installer-handoff-cursor.
