# GitHub Sync — Backlog ↔ Issues

How the Yoke backlog mirrors to GitHub issues, and the per-project switch
that turns that mirroring off.

## What syncs

Every backlog→GitHub surface routes through the
`yoke_core.domain.backlog_github_sync` helper family (issue create,
body/title updates, status comments, state close/reopen, status and flag
labels, done-transition closeout, epic-task issues, progress notes) or the
resync engine (`yoke resync`, `yoke_core.engines.resync`), which detects
and repairs drift between the DB and the linked issues. Repository authority
and a short-lived installation token resolve per project through
`yoke_core.domain.project_github_auth.resolve_project_github_auth`
(an active, verified `project_github_repo_bindings` row). The binding is the
sole outbound repository authority; `projects.github_repo` is a compatibility
display projection and never overrides it. The
resolver fails closed when the App installation is suspended, the exact
repository is unavailable, or required permissions are missing; GitHub
authentication never falls back to a project capability secret or host
credential.

## The per-project switch: `projects.github_sync_mode`

One column is the authority for whether a project's backlog mirrors to
GitHub issues at all:

| Value          | Meaning                                                              |
|---             |---                                                                   |
| `enabled`      | Default (also what `NULL` resolves to). Backlog items and epic tasks mirror to GitHub issues. |
| `backlog_only` | The backlog lives ONLY in the Yoke DB. Every GitHub issue sync surface skips or refuses for the project. |

Reader: `yoke_core.domain.projects_github_sync_mode`. The mode vocabulary
is single-sourced in `yoke_contracts.project_contract.github_sync_mode`.

Read and flip through the registered projects surface:

```bash
yoke projects get --project <slug> --field github_sync_mode
yoke projects update --slug <slug> --name <Name> --github-sync-mode backlog_only
```

`backlog_only` is independent of the GitHub App repo binding: a project can
keep the binding for code delivery (pushes, CI, deploys) while never
mirroring backlog content to that repo's issue tracker. This is the
"repo connection optional — sync off" posture.

## Backlog-only semantics

- **Item flows skip silently-and-logged.** Sync helpers invoked from item
  lifecycle flows (create, body/title sync, status comments, labels,
  close/reopen, done closeout, epic-task sync, progress notes) return
  success and print one canonical mode-language line
  (`GitHub <operation> skipped for project '<slug>':
  github_sync_mode=backlog_only ...`). The flow continues; nothing
  reaches GitHub. A backlog-only project resolves no GitHub App token — the
  skip fires before auth resolution and is never reported as an auth failure.
- **Structured-field writes with `options.sync_github_body=true` no-op
  cleanly.** The body-sync step reports success (no `sync_warning`); the
  DB write and board rebuild proceed as normal.
- **`yoke resync` names the exclusion.** Backlog-only projects are
  excluded from the GitHub fetch and from classification: their items are
  never local orphans (so `--fix` can never mass-create them as issues),
  never drift, never repair. The report prints a
  `=== GitHub Sync Disabled (per-project) ===` section naming each
  excluded project; the exit code reflects the enabled projects only.
- **Explicit issue-creating operations refuse.** `migrate_issue_to_repo`
  (cross-repo issue migration) returns non-zero with the mode-language
  message when the target project is backlog-only, instead of creating an
  issue there.

## Rebinding a project repository — ordering

Changing the verified App binding does not move existing issues. If the
backlog should not immediately sync into the replacement repository, use this
order:

1. **Sync off first:** set `github_sync_mode=backlog_only` for the
   project and verify (`yoke projects get --project <slug> --field
   github_sync_mode`).
2. **Bind verified App access:** run `yoke projects github-binding bind` with
   the project, installation id, repository id, and new `owner/repo`.
3. **Migrate intentionally or keep history:** existing `items.github_issue` /
   `epic_tasks.github_issue` numbers keep pointing at the old repo's
   issues until the explicit issue-migration flow moves them. No sync writes
   land while the project remains `backlog_only`.

Re-enable sync only after the binding and issue disposition are verified.
Rebinding before step 1 leaves a window where the next sync can create backlog
issues in the new repository.
