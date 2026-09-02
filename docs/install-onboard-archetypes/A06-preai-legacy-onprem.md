# A06 — Elena, pre-AI company, on-prem GitLab, Linux, CI/CD

**Vector:** pre-AI company · mature legacy · on-prem · Linux · **other forge
(GitLab)** · CI/CD.

Elena's org runs GitLab CE on the intranet, Jenkins on-prem, Java services on
VMs. IT will not put source on github.com. They will run a **team server** on
their network, using guided first boot on the host or the manual
`yoke self-host init` path.

## Fit / break / gaps

| | |
|---|---|
| Fits | Linux installer. Guided self-host first boot on the host, then **A team server** (reachable URL + API token) on clients. Existing folder. Skip GitHub. |
| Breaks | Every GitHub App screen is the wrong forge. Clone-from-GitHub mode cannot clone GitLab. `github_origin` parsing is GitHub-deployment-specific. Merge queue / Actions OIDC are GitHub. |
| Gaps | GitLab (or generic git) as VCS. On-prem Jenkins as CI method. |

## Transcript — installer

Linux host: `curl -fsSL https://upyoke.com/install | sh`. uv via Astral
consent `[Y/n]`. `Starting Yoke onboard…`.

## Transcript — wizard

PATH Continue. Account:

```
Where should this Yoke live?
  This machine
  A team server     the URL of your team's self-hosted Yoke server
  Set this machine up as a self-hosting server
                    Docker Compose · guided first boot
  upyoke.com
  stage.upyoke.com
```

On the intended Linux host, IT can pick **Set this machine up as a
self-hosting server**. The wizard previews `./yoke-server`,
`http://127.0.0.1:8765`, Docker/Compose, and the fact that IT owns reachable
networking and TLS. Start creates and launches the bundle, reads the reusable administrator
token from its owner-only file without printing it, and activates the host's
local connection. IT stores the
token, mints separate teammate tokens, configures the intranet URL, then picks
**Finish with server handoff**. The manual `yoke self-host init` reference in
`docs/self-host.md` remains available.

On Elena's client machine, **User:** A team server.

```
Enter your Yoke server URL.
Where your team's Yoke lives — e.g. https://api.mycompany.com.
No server yet? Paste the install one-liner on the box you want to host on and
pick Set this machine up as a self-hosting server.
```

**User:** `https://yoke.internal.corp`

```
Provide your Yoke API token.
How do you want to give Yoke your token?
  Paste it now          saved to ~/.yoke/secrets
  Read it from a file   path on disk
```

**User:** Paste it now.

```
Paste your Yoke API token.
Never shown on screen. Saved to ~/.yoke/secrets/{env}.token, owner-only.
```

Checking: `Checking Yoke token.` / `Verifying this token with your Yoke API.`

GitHub: **Skip GitHub.** (GitLab is the forge; App would be a second, forbidden
saas.)

Project: Existing folder `/srv/apps/billing`. Git remote is
`git@gitlab.internal:finance/billing.git` — **not** a configured GitHub
deployment, so `default_repo` / GitHub identity is None. Slug `billing`.
Publish to GitHub: **No — keep it local** (or auto-keep existing remote:
`project_keep_existing_remote`). Default branch from git (often `master`).
Prefix `BILL`.

No "How should Yoke manage this project on GitHub?" bind if
`project_github_repo` is empty — flow goes to board art then hosting.

Hosting: Skip (on-prem VMs, not AWS). Apply.

Yoke records a git checkout with a GitLab remote and **disabled** GitHub
automation. Jenkins is invisible.

## Transcript — `/yoke onboard`

Survey finds `Jenkinsfile`, `pom.xml`, internal registries. Strategy can
describe GitLab+Jenkins. Profile still lists GitHub binding mode
`app-binding` vs `disabled` and AWS Packs.

**User:** `disabled` GitHub; defer hosting. No `registry-oidc` (that is GitHub
Actions OIDC).

GitLab has no connect adapter (the live one is `yoke github connect`).
Issue sync cannot create GitLab issues.
Merge is local engine (`merge_queue` capability is GitHub).

Usher Route A works if no deployment_flow. A persistent AWS flow would be a
lie.

Migration: legacy DB exists, but its authoritative kind has no supported
runner pairing, so no `migration_model` can be declared for it. The step-2
governed-database box asks, and step 5 records `migration-model-setup`
`not-needed` naming that reason — work items keep `db_claim` `none`, and
the operator is told that is the complete answer rather than a gap.

## Test setup

**Reality:** flaky JUnit on Jenkins, maybe containerized. GitLab CI or
`Jenkinsfile`. Not GitHub Actions.

**Bind today:** a local `command` can wrap `mvn test` / `docker compose
run` **if** that argv is honest on the operator machine. `ci_workflow_file`
cannot name Jenkins. `merge_queue` is GitHub-only. `command-ci` against
Actions would be a lie.

**Onboard:** survey may see `Jenkinsfile` / `pom.xml`. Nothing registers
`mvn test`. No other-CI capability exists.

**Ask that should happen:** "Register a local Maven/container command, or
attest that Jenkins stays the gate and Yoke uses `implementation_review`?"
Refuse treating GitLab CI as `ci_workflow_file`. Ledger:
G-legacy-suite-unmapped, G-command-ci-misbind.

## Crux

| Requirement | Declare | Refusal | Instead |
|---|---|---|---|
| GitHub App | Already skippable | Project GitHub disabled; no issue relay | GitLab stays the forge; Yoke DB is the backlog |
| Merge target | Default branch prompt exists; forge does not | Cannot open GitHub PRs | Local merge / operator merge on GitLab |
| Deploy environment | On-prem Jenkins not a `step_runner` | Do not create AWS persistent flows | Empty default; document Jenkins as external |
| Self-host server | Guided host setup or existing URL+token | Missing Docker/Compose is named before writes; networking remains operator-owned | Run guided Start on the host or use `yoke self-host init` (`docs/self-host.md`) |

Ledger: G-forge-github-only, G-no-deploy-default-flow, G-test-setup-unasked, G-legacy-suite-unmapped, G-command-ci-misbind.
