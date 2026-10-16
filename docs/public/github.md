# GitHub

Yoke uses GitHub in several places. Configure each where it belongs — do not
hunt only in `.github/` or only in the App settings.

## Surfaces

| Use | What | Where to configure |
|---|---|---|
| **GitHub App (machine)** | Product commands that inspect/write GitHub from this machine | `yoke github connect` / `yoke github status`; GitHub Settings → Applications |
| **Git over the network** | Every push, fetch, and remote read Yoke itself runs | Connected App authorization; optional own git credentials when no authorization is stored |
| **Repo binding** | Which repo a project maps to | Project create/import; workbench **GitHub** tab |
| **Issue sync** | Backlog ↔ GitHub issues (labels, body, close) | Project `github_sync_mode` (e.g. disabled / sync modes); see [reference/github-sync.md](reference/github-sync.md) |
| **CI** | PR and push checks; full-suite authority on protected merge | Repo Actions workflows; branch protection; project `ci_workflow_file` capability naming the **test** workflow — it must be dispatchable with a `yoke_dispatch_id` input, or the binding is refused ([qa.md](qa.md)) |
| **Merge queue** | Item branches land as PRs through one `merge_group` gate | Project `merge_queue` capability — offered only with GitHub bound, `ci_workflow_file` declared, and that workflow carrying a `merge_group` trigger |
| **Delivery dispatch** | Deployment flows that trigger Actions | Delivery flows + environment protection + Action secrets/vars |
| **Runners** | Self-hosted runners for Actions | Packs / runner fleet capabilities; GitHub runner registration |
| **Permissions** | What the App or tokens may do | App install scope; org/repo permission docs in source tree |

Yoke's own git operations — the merge push, the QA lane push, the doctor's
remote reads, the deploy pipeline's tag resolution — authenticate with the
authorization `yoke github connect` stores. You do not need an SSH key or a
`gh` login for them, and an `https` or `ssh` origin works the same way. When
no authorization is stored, Git may try your existing credential helper or SSH
key without prompting. Onboarding may finish locally when publication fails. A standalone merge
with a remote refuses close-out until the candidate reaches that remote. Successful pushes name “pushed with
your own git credentials” or “pushed with Yoke GitHub access”. A broken stored
authorization never falls back to your own credentials; GitHub API features
still require the App connection.

For ordinary Git commands in registered checkouts, run
`yoke project install /path/to/checkout` after connecting. Install and refresh
converge GitHub origins to HTTPS and attach the verified Yoke helper, including
projects originally onboarded with SSH or before helper wiring existed.
Changes and skipped or refused setup are reported by the command. See
[projects.md](projects.md#checkout-github-sign-in).

Git and local GitHub API calls reuse a valid stored access token without taking
credential locks or requesting service health. Before refresh, Yoke proves the
selected service's App identity, then takes the machine and credential locks
and reads the credential again; concurrent refreshes reuse the first result.
Binding also proves the App identity before writing the project binding.
Local product App identity is checked against the installed bundle on every read.
A credential lock wait is announced after about two seconds. If it times out,
retry the command; run `yoke github status` if access keeps failing.

## Merge connectivity and issue mirroring

A project's active GitHub App repository binding determines whether a
standalone merge needs App admission, publication, and post-push checks.
`github_sync_mode=disabled` only disables issue mirroring; it does not disable
these merge gates for a connected repository.

A project without an active App binding can integrate locally and publish
with its own Git credentials. Post-push App checks stay off for these
repositories. Every standalone close-out with a remote still fetches its
default branch and proves exact candidate ancestry before recording a landing.
Failed publication or an unreadable remote preserves the lane and refuses
evidence and lifecycle close-out. A checkout with no remote proves its local
default branch instead. Issue mirroring follows its own sync mode.

The trial and real integration use `origin/<default-branch>` when that ref
exists, otherwise the local default branch. A checkout with no remote does
not fetch. Connected projects retain their publication and verification gates.

## Typical first connect

```bash
yoke github connect
yoke github status
```

Choose **All repositories** when installing the product App so new repositories
are available without another GitHub settings visit. This grants the App access
to every repository in that account; selected access remains usable. Setup and
status recommend switching selected installations and show their direct settings
link. Change the selection there, save, then run `yoke github status` to refresh.
User authorization alone does not change installation scope.

Setup's TUI opens the plain `/apps/<app>/installations/new` URL without repository
preselection. GitHub documents all repositories as the default when repository
IDs are omitted ([GitHub installation documentation](https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/migrating-oauth-apps-to-github-apps#prompt-users-to-install-your-github-app)).

Inside agent-mode setup, the GitHub step arrives as a `browser` line; see
[Agent setup](guides/agent-setup.md#browser-steps). For a standalone
agent-led connection, use `yoke github connect --json`. No browser opens;
JSON progress on stderr supplies the link, code and instructions before the
approval wait, with the final result on stdout. Present the action to the
person and continue the same command. A valid saved authorization is reused;
`--replace` requests fresh approval. `--add-installation` returns the App
installation link while reusing the saved authorization. Setup's TUI opens
these links only after an “Opening your browser…” notice and offers Ctrl-Y
copy. See [setup browser steps](start/install.md#onboard-wizard).

Optional during `yoke setup` Account/GitHub steps. The onboard GitHub
rail stays incomplete until that same `ready` contract is true — skipping
or moving to Project does not mark GitHub done. A private clone after
connect uses the App authorization; if status is not ready, the clone
preflight names `yoke github connect`.

When one-step repository creation is unavailable, setup opens GitHub's new
repository page. Create the repo, return, and choose **Check repositories**
(the default). Select the exact live, writable repository to continue. Existing
all-repositories or selected access needs no settings visit. If your repo is
absent, choose **My repository isn't listed** and enter its exact `owner/repo`.
Only a successful check that excludes it offers **Grant repo access**. Add the
repo in the opened App settings, return, and choose **Check repositories** again.
A failed refresh leaves access unknown and offers retry; **Skip GitHub** and
**Back** remain available throughout recovery.

Status reports one verdict per binding: user authorization for the merge path
(`ok` / `busy` / `broken`, proven through the same connection and token read a
local merge uses) and App installation access (`ok` / `broken`). `ready` is
true only when both are `ok`; see `yoke github status --help`. A third binding
reports the stored access token git commands actually present and when it next
renews. That one is read locally and rotates nothing, so a status check never
breaks a push in flight — and it never gates `ready`, because a machine with no
token cached yet simply mints one on its next command.

Setup also checks existing repositories live before binding them. If a successful
check cannot see your repository, add the exact `owner/repo` using the displayed
GitHub App installation settings link, then choose **Check access again**.
The link identifies the owning personal or organization installation. A failed
identity or repository-list check reports access as unknown and asks you to
restore the connection and retry; cached repository lists do not prove access.

## GitHub access changes by mode

```bash
yoke github status
```

Run this check after changing App permissions or repository access. **Hosted**
Yoke receives App webhooks for authorization, installation and repository
access changes. **Local and self-hosted** Yoke do not receive those webhooks;
they notice access changes at the next GitHub check, rather than immediately.
After returning from App settings, refresh access with **Check repositories**
for a new repo or **Check access again** for an existing one before continuing.
Issue mirroring remains a separate setting.

The workbench **GitHub** tab is the same page in every mode. It lists App
installations, this machine's or organization's personal authorization when
one is known, and each project's repository mapping. Each installation links
to its GitHub repository-access settings (**Manage on GitHub**). Hosted pages
mark installation facts **live**. Local and self-hosted pages show when each
installation was last checked; **Check now** re-verifies every bound project
in scope (`yoke projects github-binding check --project <slug>` does the same
for one project). A refused check names its reason and recovery.

## CI verdicts and session wake-ups

On the **machine running the waiting session**, with that session's Yoke
connection selected:

```bash
yoke relay status
```

The relay must be running and healthy there for CI verdict wake-ups in **every
mode: local, self-hosted and hosted**. A relay on the control-plane server or
another computer does not replace the session machine's relay. Repair the
named status refusal; `yoke relay install` repairs missing service setup.
Keep the machine awake and connected while waiting.

Yoke records the session that dispatched a CI run. Relay upkeep checks pending
runs and queues the verdict when that session's turn has ended; the session
machine's relay delivers the supported wake. A session still watching the run
receives its result through that watcher. Wake support depends on the harness
and surface; keep following a live watcher's continuation handle until it exits.

On Linux, stay logged in: the systemd user relay stops after the last logout.
Yoke requires linger to be disabled. If setup reports `relay_linger_enabled`,
follow the [Linux relay recovery](reference/linux-relay.md) before retrying.
That page owns the logout and linger procedure.

## Sync modes

Projects can run backlog-only (DB is authority, no issue sync) or sync with
GitHub issues. Public repos and permission posture constrain which modes are
safe. Prefer the workbench **GitHub** tab and project settings over editing
raw DB rows.

## Failed CI job recovery

Inspect the failed jobs with `yoke github-actions failed-log <owner/repo> <run-id> --project <project>`.
For a transient infrastructure failure, the worker holding the item claim runs
`yoke github-actions run rerun-failed ITEM RUN-ID`, then resumes the same CI/QA
wait. The registered `github_actions.run.rerun_failed` mutation derives the
repository and landing PR from the item, requires the run to match the PR's
current head and be the newest run of that workflow on the PR branch, and
records intent and outcome in the item's Progress Log. A stale head or
superseded run refuses and names the current identity to inspect; never rerun
an older run through another tool because it can cancel newer CI work.
Repair test failures in the item and commit before retrying verification.
A lost POST response reports `ci_rerun_ambiguous`: inspect the run's attempt
and status before retrying. If GitHub accepted the rerun but receipt recording
failed, restore item writes and append the returned receipt; resume the wait
without another rerun. An older serving engine names the required serving
floor; the control-plane operator must provide a serving release carrying the
function before this recovery is available.

## Operator tips

- Never treat `PREFIX-N` as a GitHub issue number — resolve via the item's
  `github_issue` field.
- Branch protection and required checks are Doctor-visible when configured.
- Secrets for deploy/CI belong in GitHub Environments or capability secret
  stores — not in committed docs.

Deep sync mechanics: [reference/github-sync.md](reference/github-sync.md).
