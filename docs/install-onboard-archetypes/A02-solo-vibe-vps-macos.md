# A02 — Priya, solo vibe-coder, DigitalOcean droplet, macOS, GitHub no CI, manual deploy

**Vector:** solo · vibe-coded · DigitalOcean/VPS · macOS · GitHub without CI · manual deploy.

Priya has a messy Next.js app on a droplet, `git push` then `ssh` + `git pull`.
GitHub is the remote; no Actions. She wants Yoke to run the delivery loop, not
replace the droplet tomorrow.

## Fit / break / gaps

| | |
|---|---|
| Fits | Local universe. Existing folder. GitHub App bind. Declare "I host this myself" in the wizard. |
| Breaks | Pack `vps-hosting` provisions AWS EC2 (`provision-ec2.sh.tmpl`), not DigitalOcean. Manual SSH deploy has no flow stage. |
| Gaps | No DO/VPS credential surface. No "manual host, no pipeline" default. |

## Transcript — public installer

Same command: `curl -fsSL https://upyoke.com/install | sh`. Darwin passes.
uv already present (she has Homebrew tooling) → no consent screen; helper
prints `Setting up Yoke…` / `Yoke v… is ready` / `Starting Yoke setup…`.
Launches `yoke setup --post-install`.

## Transcript — wizard

PATH begins directly with `{brand} is already on your PATH.` / `Continue`.

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
AWS is the one Yoke can run for you; hosting it yourself is a fine answer.
  AWS                    Yoke can manage its infrastructure
  I host this myself     Yoke applies no infrastructure
  Decide later           /yoke onboard asks again
```

**User:** I host this myself. The choice immediately records the settled
no-Yoke-managed-host posture and opens Review; there is no optional location
note screen and no AWS credential box.

Review: Apply. GitHub already saved subtitle may be
`Machine GitHub authorization is already saved; only the remaining setup writes wait for Apply.`

Hand-off: source zprofile if needed; open Claude Code, Codex, or Cursor; `/yoke onboard`.

## Transcript — `/yoke onboard`

`yoke onboard checklist init --project priya-shop --checkout ~/code/priya-shop`

Survey maps the existing app and records the no-Yoke-managed-host posture.
The confirmed profile excludes AWS Packs, credentials and managed environments;
step 4 records hosting not needed without a probe. Priya chooses merge-only
or no default, verified by readback in step 5. Manual SSH delivery remains
operator-owned. Seed work uses only that verified default; no persistent
flow or stage/prod placeholder is created.

## Test setup

Survey the Node scripts and confirm the actual suite. Register reliable project-local argv; keep a materially flaky or known-red suite review-only with exact advisory command evidence. If no suite exists, offer a minimal scaffold before an operator-attested no-tests decision. GitHub without an eligible Actions test workflow does not permit command-ci or a merge queue.

The confirmed profile, command/CI binding and immutable QA attachment follow
[test-setup.md](test-setup.md); this example is not a live setup receipt.

## Crux

| Requirement | Declare | Refusal | Instead |
|---|---|---|---|
| AWS environment | Self-hosted posture means no cloud apply; profile must not create persistent flows | `hosting-setup=deferred`; do not `deployment-flows create` targeting stage/prod | Merge-only flow or empty default |
| DigitalOcean | Generic self-hosted declaration exists; DigitalOcean apply does not | "Yoke cannot apply infrastructure for DigitalOcean yet" | Record SSH host as documentation; manual deploy stays operator-owned |
| CI | GitHub without Actions is valid; `ci_workflow_file` capability optional | QA `command-ci` unreachable → local `command` method, named reason | Do not invent a workflow file |

Ledger: G-hosting-aws-only, G-no-deploy-default-flow, G-paas-or-vps-non-aws.
