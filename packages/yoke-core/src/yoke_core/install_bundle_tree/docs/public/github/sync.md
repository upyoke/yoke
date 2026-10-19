# GitHub Sync — Backlog ↔ Issues

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [GitHub](index.md) > Issue sync
<!-- /yoke:breadcrumbs -->

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

## Issue identity and link repair

Before creating a backlog item, epic parent or task issue, Yoke adopts an
existing issue only when its complete title and outgoing body match after
whitespace normalization. Matching remains case-sensitive; a matching item
prefix alone is insufficient. Oversized bodies compare the compact mirror
that creation would send. Each sync runs one GitHub search per item-ref
title prefix: an epic parent and all its task issues share one search, and
each task is matched against those results locally. A search failure skips
adoption and creation makes new issues, with one warning naming the failed
search; that sync does not retry the search for later issues.

```bash
yoke claims work acquire --item PREFIX-N --reason "repair GitHub issue link"
yoke items github-link PREFIX-N --issue 123
yoke items github-link PREFIX-N --unlink
```

Choose the intended issue number in the project's bound repository; use
`--task-num N` for an epic task. The command requires the item's work claim,
verifies replacement issues, and rejects pull requests. It changes only the
stored link and clears item compact-mirror state; it does not close, relabel,
or comment on either issue. Read `yoke items github-link --help` for options.
The next sync uses the new link; after unlinking it can adopt an exact content
match or create an issue. Unlinking does not disable mirroring. Release the
work claim after repair if no other item work is in progress.

## The per-project switch: `projects.github_sync_mode`

One column is the authority for whether a project's backlog mirrors to
GitHub issues at all:

| Value          | Meaning                                                              |
|---             |---                                                                   |
| `enabled`      | Backlog items and epic tasks mirror to GitHub issues. An explicit enable requires an active, verified GitHub App repository binding. |
| `disabled`     | The backlog lives only in the Yoke DB. Every GitHub issue sync surface skips or refuses for the project. |

New projects default to `disabled`. Terminal setup silently leaves issue sync
off, with no issue-sync question. Connecting GitHub, binding a repository,
publishing code and approving setup do not enable mirroring. Existing projects
keep their saved mode when setup reuses their binding. A legacy `NULL`, empty, or unrecognized
stored value also resolves to `disabled` and is normalized during schema
initialization or by the repair command.

Reader: `yoke_core.domain.projects_github_sync_mode`. The mode vocabulary
is single-sourced in `yoke_contracts.project_contract.github_sync_mode`.

Enable only when the person deliberately chooses to mirror backlog content.
The App binding must be active and verified, with its required repository
permissions (including Issues write); missing permissions refuse the update.
Grant the missing App access and rebind before retrying. Public repositories
also require `--allow-public-github-sync`.

Read and change the project setting through the registered projects surface:

```bash
yoke projects get --project <slug> --field github_sync_mode
yoke projects update --slug <slug> --name <Name> --github-sync-mode enabled
yoke projects update --slug <slug> --name <Name> --github-sync-mode disabled
yoke projects github-sync-mode repair
yoke projects github-sync-mode repair --apply
```

Enabling permits subsequent syncs to file backlog items and tasks as issues;
it does not file an issue itself. Each issue creation, including the first,
returns a short notice and the GitHub issue link. A response without a URL
reports the issue number instead of inventing a host.

The repair command is a dry-run unless `--apply` is explicit. It finds
projects with a legacy, empty, or unrecognized stored mode, enabled projects
without an active verified binding, and stale repository/capability
projections. It normalizes the affected modes to `disabled`. Use `--project
<slug>` to inspect or repair one project.

`disabled` is independent of the GitHub App repo binding: a project can
keep the binding for explicitly selected CI, PR/queue, or deployment operations
while never mirroring backlog content to that repo's issue tracker. A direct
standalone merge uses the active App binding to decide whether it needs App
admission and post-push checks. Publication and freshly fetched remote
candidate ancestry are required whenever the checkout has a remote. Disabled issue mirroring does
not turn those merge gates off.
See [GitHub](index.md#merge-connectivity-and-issue-mirroring).

Standalone post-push close-out reads workflow runs with `event=push` for the
landed head SHA, then reads only those runs' check suites. Dispatched workflows
on the same commit do not hold close-out. A queued workflow with no checks yet
still counts as pending. The discovery window and 15-minute conclusion budget
are unchanged.

When a push workflow is cancelled, close-out follows the newer branch head
only after proving it contains the landed commit and has push runs for the
cancelled workflows. It reports `superseded by <full SHA>` and evaluates that
commit within the original deadline. Cancellation without that proof is a
failed CI result. Provider reads that cannot establish identity or completeness
refuse as `post_push_ci_unreadable`; restore GitHub App Actions, Checks and
Contents read access and resume the same item:

```text
yoke merge item PREFIX-N --result "<result>" --verification "<passing proof>"
```

The receipt preserves the landing identity and records the observed push
workflow URL, conclusion and evaluated head SHA in its check evidence.

Local task graphs and dispatch chains do not depend on issue mirroring. The
planning sync and its registered retry generate local queues in either mode,
before optional GitHub publication. A disabled project needs no GitHub auth
and makes no remote issue writes.

```text
yoke items github-sync PREFIX-N
yoke workflow-item epic-dispatch-chain list --epic PREFIX-N --json
```

The work holder retries this command for an already-planned graph with missing
chains, then checks the recorded queues. Existing chains, lane assignments and
queue progress remain intact; another live holder must run its own retry.
Scope finalization, dependency gates, lane activation and delivery gates still
apply. Repair requires a serving build carrying local chain generation; if a
retry reports success but chains stay absent, ask the control-plane operator to
admit that build before retrying. Do not change the project's sync mode.

## Disabled semantics

- **GitHub work skips with a mode notice.** GitHub helpers invoked from item
  lifecycle flows (create, body/title sync, status comments, labels,
  close/reopen, done closeout, epic-task sync, progress notes) return
  success and print one canonical mode-language line
  (`GitHub <operation> skipped for project '<slug>':
  github_sync_mode=disabled ...`). The flow continues; nothing
  reaches GitHub. A disabled project resolves no GitHub App token — the
  skip fires before auth resolution and is never reported as an auth failure.
  Local task-scope and lane validation can still refuse chain generation.
- **Structured-field writes with `options.sync_github_body=true` no-op
  cleanly.** The body-sync step reports success (no `sync_warning`); the
  DB write proceeds as normal.
- **`yoke resync` names the exclusion.** Disabled projects are
  excluded from the GitHub fetch and from classification: their items are
  never local orphans (so `--fix` can never mass-create them as issues),
  never drift, never repair. The report prints a
  `=== GitHub Sync Disabled (per-project) ===` section naming each
  excluded project; the exit code reflects the enabled projects only.
- **Explicit issue-creating operations refuse.** `migrate_issue_to_repo`
  (cross-repo issue migration) returns non-zero with the mode-language
  message when the target project is disabled, instead of creating an
  issue there.

Without a selected project, Doctor's `orphaned-gh-issues`,
`gh-orphan-detection`, and `wrong-repo-issues` checks report N/A with the
reason "No project selected". Use `--project` to select their project.

## Rebinding a project repository — ordering

Changing the verified App binding does not move existing issues. If the
backlog should not immediately sync into the replacement repository, use this
order:

1. **Sync off first:** set `github_sync_mode=disabled` for the
   project and verify (`yoke projects get --project <slug> --field
   github_sync_mode`).
2. **Bind verified App access:** run `yoke projects github-binding bind` with
   the project, installation id, repository id, and new `owner/repo`. If the
   checkout has no GitHub remote yet, create a private repo and bind it with
   `yoke project git bootstrap CHECKOUT --project <slug> --yes` instead.
3. **Migrate intentionally or keep history:** existing `items.github_issue` /
   `epic_tasks.github_issue` numbers keep pointing at the old repo's
   issues until the explicit issue-migration flow moves them. No sync writes
   land while the project remains `disabled`.

Re-enable sync only after the binding and issue disposition are verified; the
registered project update rejects `enabled` while that binding is unavailable.
Rebinding before step 1 leaves a window where the next sync can create backlog
issues in the new repository.
