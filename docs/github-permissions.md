# GitHub App Permissions — What Yoke Asks For, and Why

This is the user-facing rationale for the GitHub access Yoke requests: why the
connection exists, the exact repository permissions the Yoke GitHub App
declares, and what Yoke actually does with each one.

For the operator runbook (registration, private-key custody, rotation) see
[GitHub App Operations](github-app-operations.md). For the connection model
see [GitHub Connection Layers](github-connections.md). For the backlog↔issue
mirror see [GitHub Sync](../.yoke/docs/reference/github-sync.md). The machine-checked source of truth
for the permission set is
`packages/yoke-contracts/src/yoke_contracts/github_app_installation_permissions.py`.

## Permission boundary

Yoke mirrors enabled backlog issues, manages pull requests/git delivery and
starts CI/deploy workflows. The Product App declares nine baseline repository
permissions. Administration and repository Webhooks belong to separately
selected privileged authority; opting into a feature does not add an optional
per-repository grant to the Product App. App permissions are registration-wide
and presented to every installation; use a dedicated privileged binding and
selected repositories for runner-fleet authority.

Authorize through GitHub's device/install ceremonies. Installation and project
bindings store verified non-secret metadata; machine authorization retains an
owner-only rotating refresh credential. App keys stay in control-plane secret
custody, and operations use short-lived downscoped tokens.

## The connection is three separate layers

They are independent — removing one does not remove the others. This is the
model behind the "Connect a GitHub repository" screen.

| Layer | Screen section | Answers | Mechanism |
| --- | --- | --- | --- |
| **1. Machine authorization** | *GitHub identity* | Which GitHub user may this copy of Yoke act as? | GitHub **device flow** (`yoke github connect`). A rotating refresh credential is stored owner-only under `~/.yoke/secrets/`; short-lived access tokens stay in memory. |
| **2. App installation** | *App installations* | Which account/org installed the App, and which repos did GitHub grant it? | Managed entirely by **GitHub**. Yoke stores only the verified installation id, permissions, and status. |
| **3. Project ↔ repo binding** | *Project repository bindings* | Which one of the App's repositories belongs to this Yoke project? | One verified row (`project_github_repo_bindings`) — the sole authority for issue sync, PRs, Actions, and delivery. |

"The repository is verified against your GitHub authorization" means: before
storing a binding, Yoke uses *your own* user token to confirm `GET /user` →
your installations → the exact repository is actually available to that
installation, and that the repository owner matches the installation account.
It never trusts caller-supplied metadata.

## Two kinds of token

Every GitHub action runs under one of two short-lived, App-scoped tokens —
never a long-lived personal token:

- A **user-to-server token** from the device flow. This authorizes *local*
  work on the machine you authorized: git pushes over HTTPS, listing your
  repos/orgs during onboarding, and the optional repo-create step.
- An **installation token** minted server-side from the App's private key
  (`POST /app/installations/{id}/access_tokens`). This authorizes *automation*
  REST calls (issues, PRs, Actions, secrets, variables). It is minted per
  operation and scoped down to just the permissions that operation needs.

Both are bounded by the App's declared permissions below.

### Which one an operation runs under

An operation names the *weakest* authority that can perform it, and resolution
honors that name. Only work attributed to a person genuinely needs the
user-to-server token; work the installation is itself authorized to do falls
through to an installation token when the machine authorization is
unavailable, instead of refusing something the binding already covers. When
neither path produces a token, the user-authorization failure is the one
reported, because reconnecting is the repair on a machine bound to user
authority.

Merging is where the distinction is load-bearing, so the merge engine settles
it before any merge work rather than discovering it afterwards:

| Merge route | Authority | Why |
| --- | --- | --- |
| **Direct merge** — land in the checkout, publish the base branch, prove the pushed commit's checks | Installation | Nothing is attributed to a person; the machine's stored GitHub credential carries the push and Checks: read carries the proof |
| **Pull-request merge** — open a PR, wait on its checks, merge it | User | The pull request is opened as *you* |

A merge whose checkout has no remote never reaches GitHub and needs no
authority at all. Classifying up front is what keeps an unavailable
authorization from surfacing only after the branch has already landed — a
merge that succeeded while its verification reported failure.

## Permissions at a glance

Authoritative source:
`packages/yoke-contracts/src/yoke_contracts/github_app_installation_permissions.py`.

### Baseline — requested of every connection

| Permission | Access | Purpose |
| --- | --- | --- |
| **Metadata** | read | GitHub-mandated floor; repo/commit lookups + issue search |
| **Issues** | write | Mirror your backlog to GitHub Issues (issues, comments, labels, sub-issues) |
| **Pull requests** | write | Open a PR from the worktree branch into your default branch |
| **Contents** | write | Deliver code over git — push branches, merge the PR, commit, clean up |
| **Workflows** | write | Manage the CI/CD workflow files Yoke ships into `.github/workflows/` |
| **Actions** | write | Kick off (dispatch) the deploy/CI workflows Yoke orchestrates |
| **Checks** | read | Read a PR's CI results and merge only when green |
| **Secrets** | write | Seed the encrypted deploy credentials your generated pipelines need |
| **Variables** | write | Set non-secret Actions config (CI-enable flags, runner routing) |

### Privileged — separate authority, outside the Product baseline

| Permission | Access | Only if you… |
| --- | --- | --- |
| **Administration** | write | …let Yoke create a repo for you, create a deploy environment, apply merge-queue declarations, or run a runner fleet |
| **Webhooks** (`repository_hooks`) | write | …run your own self-hosted GitHub Actions runner fleet |

A contract test actively enforces that Administration and Webhooks stay out of
the baseline set.

## What each permission does

### Baseline

**Metadata: read** — The floor GitHub requires of every App; it cannot be
dropped and it is the guaranteed minimum stamped on every token Yoke mints.
Explicitly used for: issue lookup via `GET /search/issues` (backlog↔Issues
sync, and the health check that hunts for stray Yoke-tagged issues — GitHub
gates issue *search* under Metadata, not Issues); onboarding probes that read
your repository and its latest commit to tell whether it exists / is empty / is
populated before writing anything; and a cheap pre-merge auth check.

**Issues: write** — The backlog↔Issues mirror, Yoke's core value. Creating an
issue per backlog item and epic-task, updating title/body, opening and closing
on status changes, posting status-change **comments**, creating and applying
the `status:*` / `worktree:*` **labels** Yoke tracks work with, linking
epic-task issues as **sub-issues** under their parent, and deleting a mirrored
issue (via GraphQL, since REST has no issue-delete). GitHub bundles comments
and labels under the Issues permission, so this one grant covers the whole
mirror — no extra permission needed. Only fires when a project has sync
enabled; new projects default to `disabled`, which does zero issue writes.

**Pull requests: write** — **Opening** a pull request from the worktree branch
into your default branch when you ship a work item (`/yoke usher`), plus the
agent-driven "open a PR" command. This permission is specifically for
*creating* PRs; merging the PR is authorized by Contents: write, and the
find-PR and mergeability reads run at Pull requests: read.

**Contents: write** — Delivering your code over git. Pushing the worktree
branch, pushing the base branch when it is ahead, **merging the PR** (`PUT
…/pulls/{n}/merge`), committing the done-state, deleting the now-merged branch,
and pushing preview branches for push-triggered environments. Reading
repository files (e.g. checking a deploy workflow file during setup) rides the
same grant. Git talks to GitHub over HTTPS using a short-lived token
(`x-access-token`), and the token is never written to your `.git/config` or the
stored remote URL. Yoke's own remote operations carry it as a URL-scoped
`http.extraheader` supplied per command; a URL-scoped credential helper
installed into onboarded checkouts serves the git commands people run in their
own shells. See [github-credentialed-git.md](github-credentialed-git.md).

**Workflows: write** — So the App may manage the GitHub Actions workflow files
Yoke ships into `.github/workflows/` (a CI workflow plus deploy/hotfix/smoke
pipelines). GitHub specially protects workflow files: an app needs this
dedicated permission, on top of Contents, before it may create or change
anything under `.github/workflows/`. See the hygiene note below on the current
exercised level of this grant.

**Actions: write** — Starting the workflows Yoke orchestrates for deploy/CI
(`POST …/actions/workflows/{workflow}/dispatches`). GitHub classifies
*triggering* a run as a write. Merely *watching* a run — its status, jobs, and
logs — needs only read, and Yoke uses read-scoped tokens for exactly that. The
write level is spent only at the moment a run is started. Only fires for
projects with a GitHub-Actions deploy stage.

**Checks: read** — Before merging a PR, reading its CI check-runs on the head
commit (`GET …/commits/{sha}/check-runs`) and merging only if they pass.
Strictly read-only — Yoke never creates or re-runs a check — and it uses the
modern Check Runs API, not the legacy commit-status API. Its consumers are the
PR-merge gate and the post-push proof a direct standalone landing runs against
the commit it just published; the second reads under installation authority,
because a direct merge is authorized that way. (The deploy-branch CI advisory
reads workflow-run status under Actions: read, not this permission.)

**Secrets: write** — Seeding the SSH deploy credentials (key, host, user) that
Yoke's generated deploy workflows need to reach your server. Each value is
sealed with libsodium before upload; GitHub only ever accepts already-encrypted
values and never lets anything read a secret back. Only fires when you set up
the webapp/VPS deploy pipeline — a backlog + PR + CI user never writes a secret.
Onboarding treats a missing Secrets grant as non-fatal: the binding still
records; only the deploy step is gated.

**Variables: write** — Setting non-secret GitHub Actions variables (CI-enable
flags, the runner-fleet routing variable). This write is only reached through
the operator CI/runner-fleet arming command; a normal connect-my-repo user
never triggers it. The read counterpart (runner status) needs only Variables:
read.

### Privileged (opt-in)

**Administration: write** — Only when you opt into heavier setup, on four
write paths: creating a brand-new repository for you during onboarding (**off
by default**, gated behind an explicit allow flag; otherwise Yoke blocks with
manual instructions), creating the deployment **environment** on your
repository for automated deploys (silently skipped if not granted), standing
up a self-hosted runner fleet, and applying the declared merge-queue ruleset
plus ``allow_auto_merge`` from ``.yoke/merge-queue.json`` via
``yoke github merge-queue apply`` (fails closed when Administration is
absent). If you attach a repository you already have and never retune the
queue from Yoke, you never need this. Two other Administration touches —
reading branch protection, reading runner status — are Administration:
**read**, and both degrade to a warning when Administration is absent.

**Webhooks (`repository_hooks`): write** — Only if you run your own GitHub
Actions runner fleet. Your infrastructure code (Pulumi) creates a repository
webhook on the `workflow_job` event, secured with an HMAC signing secret, so
your runners know when a job is queued. This is a **repository** webhook,
distinct from the App's own global webhook. Never touched by issue sync, PRs,
or deploys.

## What Yoke deliberately never requests

Each of these is absent from the code, not merely unlisted:

- **No Releases API** — Yoke never creates GitHub releases.
- **No Milestones** — the Issues grant is never used for milestones.
- **No Deployments API** — Yoke tracks delivery gates in its own database; it
  never creates GitHub deployment objects.
- **No Packages / GHCR on your repository** — per-project images go to a
  cloud container registry; Yoke's own server image is separate.
- **No Pages, and no commit-status write** — Yoke *reads* checks instead of
  writing commit statuses.
- **No organization, members, teams, or collaborator permissions** — the
  entire contract is repository-scoped.
- **No email / `user:email` scope** — the device flow reads only your login and
  numeric id.
- **Branch protection and queue policy are privileged** — ordinary reads warn
  when required protection is absent; applying a declared merge-queue ruleset
  requires separately granted Administration authority.
- **No classic OAuth scopes at all** — GitHub Apps derive access from
  installation permissions, not scopes. The device flow sends only a client id.

## How your access and credentials are protected

- **Least-privilege token downscoping.** The App installation holds the
  baseline grant, but every individual REST call mints a fresh token scoped to
  just that operation — an issue read carries `issues:read`, a workflow dispatch
  carries `actions:write`. There is no long-lived project token.
- **The private key stays in the control plane.** For hosted deploys, CI relays
  typed calls through Yoke's control plane rather than ever holding the App key;
  the key lives only in a secrets manager, never in CI, runner disks, or logs.
- **Sync is off by default.** New projects are `disabled` — the backlog
  lives only in Yoke's database and every Issues-write surface refuses until you
  explicitly enable sync.
- **You can unwind any layer independently** — disconnect the machine identity,
  unbind one project, or uninstall the App in GitHub — without cascading.
- **Bindings are verified against your own GitHub authorization** before they
  are stored, and re-verified server-side.
- **Secrets are sealed before upload and are write-only** — GitHub never returns
  a secret value, and Yoke never logs one.

## Registration review

Review requested and exercised authority separately. Workflows write permits
workflow-file delivery even where a path currently reads through an App token
and pushes through machine authorization. Secrets/Variables remain baseline
registration grants, while their write consumers are deploy and CI/runner
setup. A permission-tier change requires changing the registration contract
and affected consumers together; runtime token downscoping does not shrink
what a compromised registration key could request. The operator runbook owns
registration, selected repository scope and privileged binding review.

## Source of truth

- Permission contract:
  `packages/yoke-contracts/src/yoke_contracts/github_app_installation_permissions.py`
- Operator runbook (registration, key custody, rotation):
  [GitHub App Operations](github-app-operations.md)
- Connection model (identity / installation / binding):
  [GitHub Connection Layers](github-connections.md)
- Backlog↔issue mirror and the per-project sync switch:
  [GitHub Sync](../.yoke/docs/reference/github-sync.md)
