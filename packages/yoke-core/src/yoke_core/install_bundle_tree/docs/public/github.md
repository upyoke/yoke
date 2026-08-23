# GitHub

Yoke uses GitHub in several places. Configure each where it belongs — do not
hunt only in `.github/` or only in the App settings.

## Surfaces

| Use | What | Where to configure |
|---|---|---|
| **GitHub App (machine)** | Product commands that inspect/write GitHub from this machine | `yoke github connect` / `yoke github status`; GitHub Settings → Applications |
| **Repo binding** | Which repo a project maps to | Project create/import; workbench **GitHub** tab |
| **Issue sync** | Backlog ↔ GitHub issues (labels, body, close) | Project `github_sync_mode` (e.g. disabled / sync modes); see [reference/github-sync.md](reference/github-sync.md) |
| **CI** | PR and push checks; full-suite authority on protected merge | Repo Actions workflows; branch protection; project `ci_workflow_file` capability when used |
| **Delivery dispatch** | Deployment flows that trigger Actions | Delivery flows + environment protection + Action secrets/vars |
| **Runners** | Self-hosted runners for Actions | Packs / runner fleet capabilities; GitHub runner registration |
| **Permissions** | What the App or tokens may do | App install scope; org/repo permission docs in source tree |

## Typical first connect

```bash
yoke github connect
yoke github status
```

Optional during `yoke onboard` Account/GitHub steps.

Status reports one verdict per binding: user authorization for the merge path
(`ok` / `busy` / `broken`, proven through the same connection and token read a
local merge uses) and App installation access (`ok` / `broken`). `ready` is
true only when both are `ok`; see `yoke github status --help`. Under an
owner-only `<env>-db-admin` connection, status and a local merge both prove
through the https plane that connection administers, so
`yoke --env prod-db-admin github status` answers the same as
`yoke github status` on a machine connected to `prod`.

## Sync modes

Projects can run backlog-only (DB is authority, no issue sync) or sync with
GitHub issues. Public repos and permission posture constrain which modes are
safe. Prefer the workbench **GitHub** tab and project settings over editing
raw DB rows.

## Operator tips

- Never treat `PREFIX-N` as a GitHub issue number — resolve via the item's
  `github_issue` field.
- Branch protection and required checks are Doctor-visible when configured.
- Secrets for deploy/CI belong in GitHub Environments or capability secret
  stores — not in committed docs.

Deep sync mechanics: [reference/github-sync.md](reference/github-sync.md).
