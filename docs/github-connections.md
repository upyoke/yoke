# GitHub Connection Layers

Yoke's GitHub connection is three separate things. They work together, but
removing one does not silently remove the others.

## 1. Machine authorization

This answers: **which GitHub user may this copy of the Yoke CLI act as?**

`yoke github connect` opens GitHub's device-authorization flow. After GitHub
approves it, Yoke records public App and user metadata in the selected machine
config, normally `~/.yoke/config.json`. The rotating refresh credential lives
in an owner-only file under `~/.yoke/secrets/` named like
`github-app-user-<generated-id>.json`. Short-lived access tokens stay in the
running process; they are not written to machine config, Git remotes, project
rows, or reports.

This is machine/config scoped, not Yoke-actor scoped. The control-plane DB does
not currently store a GitHub user authorization on an actor. A Yoke actor token
signs the machine into Yoke; the GitHub App user authorization separately lets
the local CLI prove a GitHub user identity and perform local repository work.

GitHub integration is optional. A local universe running backlog-only installs
no App and grants upyoke no repository access. For users who choose GitHub
automation, the CLI contains the non-secret public identity of **Yoke by
upyoke.com**, so the convenience path needs no App flags:

```bash
yoke github connect
yoke github status
```

Installing an upyoke-owned App is a real trust boundary: even though device
authorization and API calls travel directly between the local CLI and GitHub,
the App owner retains App authority over repositories selected in GitHub. A
local or self-host operator who does not want that trust relationship supplies
their own complete App profile. An HTTPS hosted or team-server connection uses
the complete public profile advertised by that service and ignores ambient App
metadata.

## 2. GitHub App installation

This answers: **which account or organization installed the App, and which
repositories did GitHub grant it?**

The installation is managed by GitHub. It belongs to a GitHub user or
organization and can cover all repositories or selected repositories. Yoke
stores the verified installation identity and permission state, but GitHub is
the authority for installing the App, changing repository access, suspending
it, or uninstalling it.

The baseline product App deliberately lacks repository Administration. It can
work with repositories granted to the installation, but it cannot silently
create or fork a repository. The onboarding flow therefore opens GitHub for
manual repository creation and App access, then lets the user return and check
the exact live repository. A separately configured development/operator App
may offer privileged operations only when its verified permissions allow them.

## 3. Project repository binding

This answers: **which one of the App's repositories belongs to this Yoke
project?**

The control plane stores one verified row in
`project_github_repo_bindings`, plus a non-secret `github` project capability.
That binding carries the exact App installation id, repository id, GitHub API
origin, repository name, status, and permissions. It is the authority for
issue sync, pull requests, Actions, and other project automation.

The server uses the App installation to mint a short-lived installation token
when project automation runs. It does not store a long-lived project GitHub
token. `projects.github_repo` is only a display projection of the verified
binding, and `projects.github_sync_mode` stays `backlog_only` until the binding
is active and verified.

## Disconnecting the right layer

| Goal | Operation | What remains |
| --- | --- | --- |
| Stop this machine from acting as the GitHub user | `yoke github disconnect` | GitHub's App installation and every project binding remain |
| Stop one Yoke project from using its repository | `yoke projects github-binding unbind --project <slug>` | Machine authorization, the GitHub App installation, and other project bindings remain |
| Revoke the GitHub user authorization everywhere | Revoke the App authorization in GitHub Settings | The local Yoke config becomes unusable and should also be disconnected; App installations remain unless separately removed |
| Remove or narrow App access for an account/org | Change or uninstall **Yoke by upyoke.com** in GitHub Settings | Machine config may remain, but removed repositories make affected bindings unavailable |

`yoke github disconnect` removes the selected config's GitHub authorization,
deletes its owned refresh credential when no other supported config owns it,
and removes only Yoke-owned URL-scoped Git credential helpers from registered
checkouts. It preserves ambient or user-managed Git helpers. It does not call
GitHub to revoke authorization or uninstall the App, and it does not unbind a
project.

Project unbind deletes the project's binding, `github` capability, and any
retired project GitHub credential residue; clears the display projection; and
puts the project in `backlog_only` mode. It leaves the GitHub installation
record intact so another project or a later rebind can use it. Rebinding
requires selecting and live-verifying the exact repository; GitHub sync can be
enabled only after that binding is active.

For the safe order when changing an already-bound project's repository, see
[GitHub sync](github-sync.md). For why Yoke requests each repository permission
and what it does with them, see
[GitHub App Permissions](github-permissions.md). App registration, permission,
and key-custody operations are documented in
[GitHub App Operations](github-app-operations.md).
