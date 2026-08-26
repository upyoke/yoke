# A02 — Priya, solo vibe-coder, DigitalOcean droplet, macOS, GitHub no CI, manual deploy

**Vector:** solo · vibe-coded · DigitalOcean/VPS · macOS · GitHub without CI · manual deploy.

Priya has a messy Next.js app on a droplet, `git push` then `ssh` + `git pull`.
GitHub is the remote; no Actions. She wants Yoke to run the delivery loop, not
replace the droplet tomorrow.

## Fit / break / gaps

| | |
|---|---|
| Fits | Local universe. Existing folder. GitHub App bind. Skip hosting in the wizard. |
| Breaks | Hosting subtitle is "AWS for now". Pack `vps-hosting` provisions AWS EC2 (`provision-ec2.sh.tmpl`), not DigitalOcean. Manual SSH deploy has no flow stage. |
| Gaps | No DO/VPS credential surface. No "manual host, no pipeline" default. |

## Transcript — public installer

Same command: `curl -fsSL https://upyoke.com/install | sh`. Darwin passes.
uv already present (she has Homebrew tooling) → no consent screen; helper
prints `Setting up Yoke…` / `Yoke v… is ready` / `Starting Yoke onboard…`.
Launches `yoke onboard --post-install`.

## Transcript — wizard

PATH: Continue on the install summary; PATH already OK →
`{brand} is already on your PATH.` / `Continue`.

Account: **This machine.** Universe summary Continue.

GitHub: **Connect GitHub.** Checking screen:
`Connecting the Yoke GitHub App.` /
`A browser will open. Enter the one-time code shown here.` /
`Authorization happens in GitHub; Yoke never asks you to paste a GitHub secret.`
Device code line: `Enter code {user_code} at {verification_uri}`.
Then: `Install or configure the App at {install_url}`. She grants the existing
repo. Success details from `github_machine.status`.

Project:

```
Set up a project.
  Existing folder on my machine
```

**User:** Existing folder.

```
Point at your project folder.
Where's the code on this machine? Yoke makes it a git repo if it isn't.
```

**User:** `~/code/priya-shop`

Inspect finds origin `github.com/priya/shop`. Slug `priya-shop`. Friendly name
`Priya Shop`. Publish offer **auto-skipped** (`has_remote` — "re-homing an
existing remote is a separate capability"). Default branch detected from the
repo (not the `main` prompt). Prefix suggested `PRIY`.

```
How should Yoke manage this project on GitHub?
Bind this project to a repository the Yoke GitHub App can access, or keep
it disabled.
  Use connected repo              bind this repo using existing App access
  Add repo access                 open GitHub to change app access
  Skip GitHub for this project    disabled
```

**User:** Use connected repo.

Board art: design ASCII header, continue.

Hosting:

```
Connect your hosting provider?
AWS for now. One click creates the deploy credential; paste its two values below.
  1  Open the one-click link (creates the IAM user + access key):
     {quick_create_url or: run `yoke aws admin-link` from an installed Yoke build for the one-click link}
  2  Paste the two values — here in the wizard, never into an AI chat:
     Access key ID
     Secret access key
  Stays on this machine (~/.yoke/secrets/capability-secrets/priya-shop/aws-admin/) —
  operator-attended; CI only ever gets scoped OIDC roles minted later.
  Save & verify
  Skip for now
```

**User:** Skip for now. (she has a droplet, not AWS)

Review: Apply. GitHub already saved subtitle may be
`Machine GitHub authorization is already saved; only the remaining setup writes wait for Apply.`

Hand-off: source zprofile if needed; open Claude Code, Codex, or Cursor; `/yoke onboard`.

## Transcript — `/yoke onboard`

`yoke onboard checklist init --project priya-shop --checkout ~/code/priya-shop`

Repo survey reads `package.json`, README, no `.github/workflows`. Strategy
docs describe the shop. Profile proposal still lists AWS Packs + stage/prod.

**User at stop 1:** drop `aws-admin` / Pulumi / `registry-oidc`; keep
`webapp-scaffold` mapped (existing app → `scaffold-install=not-needed`).
Ask for a **manual** delivery path. Skill has no Pack for `ssh git pull`.

Step 4: `yoke projects capability has --project priya-shop --cap-type aws-admin`
fails → defer hosting. Step 7 deferred.

Step 5 may still `yoke projects site create`, `environment create --environment
stage` / `prod`, and `yoke deployment-flows create` if the (unadjusted)
profile included them. If a default flow is written, later
`yoke items create` uses it (`deploy-defaults get`).

Seed work: issues for "tame the repo" / "describe the droplet". If a persistent
flow was registered, Usher Route B will try to run it against an environment
that has no AWS apply.

## Test setup

**Reality:** vibe-coded Node shop. Maybe a leftover `npm test` script; no
`.github/workflows`. Flaky or empty if present.

**Bind today:** local `command` method if a real argv is registered. No
Actions file → do not declare `ci_workflow_file`. `merge_queue` requires
that capability plus GitHub — she has GitHub, not a queue.

**Onboard:** survey may see `package.json` scripts; profile does not propose
registering them. Writing `verification_profiles.test_command` would not
create the gate.

**Ask that should happen:** "Register `npm test` as `quick`, attest no
trustworthy suite, or scaffold?" Recommend register if the script exists
and exits 0 on main; else attested no-tests. Never invent Actions.

## Crux

| Requirement | Declare | Refusal | Instead |
|---|---|---|---|
| AWS environment | Hosting step already skippable; profile must not create persistent flows after skip | `hosting-setup=deferred`; do not `deployment-flows create` targeting stage/prod | Merge-only flow or empty default |
| DigitalOcean | Missing. Should be a hosting provider row next to AWS, or a "existing VPS, no Yoke apply" posture | "Yoke cannot apply infrastructure for DigitalOcean yet; skip cloud apply" | Record SSH host as documentation; manual deploy stays operator-owned |
| CI | GitHub without Actions is valid; `ci_workflow_file` capability optional | QA `command-ci` unreachable → local `command` method, named reason | Do not invent a workflow file |

Ledger: G-hosting-aws-only, G-no-deploy-default-flow, G-paas-or-vps-non-aws, G-test-setup-unasked, G-no-tests-posture, G-ci-workflow-undeclared.
