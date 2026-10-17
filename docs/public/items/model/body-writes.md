# Body write path

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Items](../index.md) > Body writes
<!-- /yoke:breadcrumbs -->

Read the canonical structured-field write and body-rendering pipeline. The [database reference](../../databases/reference.md) owns shared payload conventions.

## Body Write Path

**`items.body` is a virtual rendered field.** Not stored in the DB. Read via `items get PREFIX-N body`, which renders on demand from structured fields via `render_body.py`. Raw body writes were removed. All content must go through structured field writes.

### Structured field writes (the only supported path)

All body content reaches the database through structured field writes. The agent path is the Yoke function-call surface (`items.structured_field.replace`, `items.structured_field.append_addendum`, `items.structured_field.section_upsert`, `items.structured_field.section_append`); see [index.md](../../functions/index.md). Operator/debug callers use the matching CLI adapter:

```
Agent calls items.structured_field.replace via POST /v1/functions/call (or the in-process dispatcher)
 |
 v   (the operator/debug CLI adapter shown below dispatches the same function id)
yoke items structured-field replace <id> --field <structured-field> --stdin
 |
 v
execute_structured_write() writes the structured field to DB
 |
 +---> GitHub sync (options.sync_github_body)
```

Reading `items get PREFIX-N body` renders on demand from all structured fields. When you already have a real artifact file, the same command can read from a body file instead of stdin.

Valid structured fields are `spec`, `design_spec`, `technical_plan`,
`worktree_plan`, `shepherd_log`, `shepherd_caveats`, `test_results`, and
`deploy_log`.

Shepherd subagents (PM, Architect) write structured content during lifecycle transitions (e.g., spec, technical plan, shepherd log/caveats) using the same path.

### Error Propagation

| Step | Owner | Error Handling | Silent Failure Risk |
|------|-----------|---------------|---------------------|
| DB write | `items.structured_field.*` through the Yoke function-call dispatcher | Python prints to stderr and exits nonzero | **Low** — stderr propagates to caller |
| GitHub sync | `yoke_core.domain.backlog_github_sync` helpers | Returns nonzero on failure; sync failures are recorded in DB when invoked from backlog mutations | **Low** — failure is tracked and visible |

### Project-Aware GitHub Sync

GitHub sync operations route through the Python-owned `yoke_core.domain.backlog_github_sync` helper family and service-client entrypoints. Repo and credential resolution flow through the canonical project-auth helper at `yoke_core.domain.project_github_auth.resolve_project_github_auth`, which returns the verified binding's `owner/repo` and a short-lived bearer token.

**One GitHub contract for every project.** Every registered project resolves through the same surface; no project slug is a silent special case for ambient repo/auth. Project GitHub automation uses a verified GitHub App repo binding plus a short-lived App token. `projects.github_repo` is only a compatibility display projection; legacy project-secret rows are not a live GitHub auth storage shape.

There is no separate fallback chain: per-project token env-var lookup, project token-file lookup, and silent host-credential fallback are not part of the resolution path.

**Fail-closed on missing or broken auth.** When the resolver cannot produce a usable repo + App token (missing binding, missing installation, removed repo access, missing permission, private-key/config failure, or GitHub REST transport failure), it raises a typed diagnostic with a concrete `repair_command_hint`. Yoke-owned callers surface the diagnostic instead of silently falling through to host credentials or treating the remote as empty. Operators repair by connecting GitHub, adding repository access, binding the project repo, or switching the project to disabled. The runtime never instructs the operator to authenticate at the host CLI level as the answer to a project-auth/config problem. GitHub itself failing while the installation token is minted — a 5xx, a rate limit, a network failure or timeout — is not a project-auth problem: it raises `github_unavailable` (handlers report that code instead of `project_auth_error`) with the HTTP status in the message and a retry recovery, and retrying callers (workflow dispatch, CI watches, landing readbacks) treat it as transient. A GitHub refusal of the App or its installation stays `token_mint_failed`, naming the status and the repair it implies: 401 the App JWT (issuer, private key, clock), 403 the installation's access, 404 a missing installation, 422 the requested repository or permissions.

**Cross-project coverage.** Item sync, status comments, issue close/reopen, body/title sync, resync repair, and doctor GitHub checks all route through the canonical resolver. Resync iterates per project; each iteration calls `resolve_project_github_auth(project)` and uses bearer-token REST calls for that project. Doctor's GitHub orphan and wrong-repo checks validate label coverage and confirm that each item's GitHub issue exists in the correct repo for its project.

**Per-project sync switch precedes auth.** A project with `projects.github_sync_mode='disabled'` never reaches the resolver: every sync helper skips it with one mode-language log line (return code 0, flows continue), and resync excludes it from fetch/classification/repair. The skip is policy, not an auth failure — a disabled project needs no GitHub authorization. See [github-sync.md](../../github/sync.md).

### GitHub issue body size limit

GitHub rejects issue bodies above ~65,536 characters. Before calling GitHub's issue-body update endpoint, `items sync-body` and the shared body-update helper measure the rendered Yoke body against a conservative threshold (~62KB) defined in `yoke_core.domain.backlog_github_body_budget`. When the rendered body fits, full-body sync proceeds normally. When it exceeds the threshold, the helpers route to the **compact mirror** path instead.

**Compact mirror contents.** The compact mirror is the substitute body written to GitHub when the full rendered body is over budget. It contains item title, `PREFIX-N`, project, status, lifecycle state, an explicit note that the Yoke DB holds the canonical full body, key commands/links, and the latest evidence summary. The Yoke DB retains the full body — nothing is lost; the mirror just replaces what gets pushed to GitHub.

**Degradation reporting.** Compact-mirror sync is reported by the structured-write side-effect surface as `degraded_body_budget`, distinct from a successful full-body sync and distinct from an auth/config failure. Auth/config failures take precedence: if `resolve_project_github_auth` fails, no GitHub call is made and the surface reports the auth/config diagnostic, not a body-budget degradation.

**Unified across paths.** Issue create/reuse, lifecycle transitions, and structured-field side-effect syncs all use the same full-body vs compact-mirror contract — no path-specific drift.

**Backfill command.** Oversized-body backfill is an operator-maintenance repair for items already linked to GitHub issues whose rendered bodies exceed the budget. The repair identifies oversized rows, resyncs each one through the compact-mirror path, and is rerunnable on partial failure — previously-completed items are no-ops because they already match the compact-mirror state. It does not emit noisy comment chunking; one compact body per linked issue.

### Canonical Write Pattern

All agents should use structured field writes. Do not call lower-level item helpers directly, do not edit `.md` files and hope the content propagates. Raw body writes are unsupported.

## Related

- [QA CLI](../../verification/qa-cli.md)
- [Item model](items.md)
