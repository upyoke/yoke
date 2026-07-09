# DB Reference — qa Domain CLI and Body Write Path

Operator-facing CLI for the QA platform tables and the canonical body write/render pipeline. Cross-link back from [db-reference.md](../db-reference.md) for entry points, the domain catalog, table schemas, status lifecycle, and common pitfalls.

## qa domain CLI

Python owner: `yoke_core.domain.qa`. Public command examples use the installed
Yoke CLI, which dispatches the registered `qa.*` function ids:

- `yoke qa requirement add|add-batch|auto-create-for-item|list|get|update ...`
- `yoke qa run add|complete|record-verdict|list ...`
- `yoke qa artifact presign|add ...`
- `yoke qa gate-summary ...`

All CRUD logic for the `qa_requirements`, `qa_runs`, and `qa_artifacts` tables
lives in `yoke_core.domain.qa`; that module name is implementation authority,
not an agent-facing command recipe. Full platform documentation:
[qa-platform.md](../qa-platform.md).

```sh
# Add an item-bound review requirement
yoke qa requirement add \
 --item YOK-N --qa-kind implementation_review --qa-phase verification

# List requirements
yoke qa requirement list --item YOK-N

# Get a single requirement
yoke qa requirement get --requirement-id 1

# Update a mutable field on an existing requirement
yoke qa requirement update --requirement-id 4309 --field blocking_mode --value non_blocking
yoke qa requirement update --requirement-id 4309 --field success_policy --value "$policy_json"

# Record a QA run for that item-bound review requirement
yoke qa run add \
 --requirement-id 1 --executor-type agent --qa-kind implementation_review --verdict pass

# Epic-task review verdicts use the workflow-item helper path
yoke workflow-item epic-task review-insert \
 --epic 833 --task-num 5 --verdict pass --body "Review passed"

# List runs
yoke qa run list --requirement-id 1

# Attach an artifact
yoke qa artifact add \
 --requirement-id 1 --run-id 1 --artifact-type screenshot \
 --artifact-handle '{"backend":"local","path":"/tmp/img.png"}'

# Preview blocking QA gaps before a reviewed-implementation transition
yoke qa gate-summary --item YOK-N --target reviewed-implementation --json
```

| Subcommand | Args | Description |
|---|---|---|
| `yoke qa requirement add` | `--item PREFIX-N --qa-kind K --qa-phase P [opts]` | Insert one item-attached requirement |
| `yoke qa requirement add-batch` | `--item PREFIX-N (--rows-file PATH \| --stdin)` | Insert item-attached requirements atomically |
| `yoke qa requirement auto-create-for-item` | `--item PREFIX-N` | Materialize default requirements for one item |
| `yoke qa requirement list` | `[--item PREFIX-N \| --epic-id N \| --deployment-run-id ID]` | List requirements |
| `yoke qa requirement get` | `--requirement-id N` | Get one requirement |
| `yoke qa requirement update` | `--requirement-id N --field FIELD (--value VALUE \| --null)` | Update one mutable field |
| `yoke qa run add` | `--requirement-id N --executor-type T [--qa-kind K] [--verdict V] [opts]` | Insert a run |
| `yoke qa run complete` | `--requirement-id N --run-id N [--verdict V] [--execution-status S] [opts]` | Complete a previously recorded run |
| `yoke qa run record-verdict` | `--requirement-id N --executor-type T --verdict V [opts]` | Record a one-shot verdict |
| `yoke qa run list` | `[--requirement-id N]` | List runs |
| `yoke qa artifact presign` | `--requirement-id N --run-id N --filename NAME [--content-type CT]` | Mint a durable upload target |
| `yoke qa artifact add` | `--requirement-id N --run-id N --artifact-type T --artifact-handle JSON [opts]` | Insert an artifact row |
| `yoke qa gate-summary` | `(--item PREFIX-N \| --epic-id N --task-num K) --target reviewed-implementation\|implemented` | Read blocking QA gaps for a transition |

No public QA init, requirement-waive, run-get, or artifact-list adapter is
registered in this branch. Schema initialization belongs to DB setup/migrations.
Waive, single-run get, and artifact-list remain implementation/domain
capabilities until a public adapter is registered; do not teach fake
`yoke qa ...` commands for them.

**When to use which mutator.** `requirement-update` changes the *policy* of an
existing requirement — tighten a success policy, move a requirement between
`blocking` and `non_blocking`, bind it to a different `target_env`, or clear a
nullable field. It preserves the requirement identity, so linked runs and
artifacts stay attached. Use `requirement-add` when the *verification surface
itself* needs to change — for example, swapping from `unit_test` to
`integration` — since that is a different requirement. `requirement-update`
refuses to mutate `qa_kind` for exactly that reason.

Exit codes: 0 = success, 1 = error/not found, 2 = usage error

## Body Write Path

**`items.body` is a virtual rendered field.** Not stored in the DB. Read via `items get YOK-N body`, which renders on demand from structured fields via `render_body.py`. Raw body writes were removed. All content must go through structured field writes.

### Structured field writes (the only supported path)

All body content reaches the database through structured field writes. The agent path is the Yoke function-call surface (`items.structured_field.replace`, `items.structured_field.append_addendum`, `items.structured_field.section_upsert`, `items.structured_field.section_append`); see [functions.md](functions.md). Operator/debug callers use the matching CLI adapter:

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
 +---> Board rebuild (options.rebuild_board)
```

Reading `items get YOK-N body` renders on demand from all structured fields. When you already have a real artifact file, the same command can read from a body file instead of stdin.

Valid structured fields are:
`spec`, `design_spec`, `technical_plan`, `worktree_plan`, `shepherd_log`, `shepherd_caveats`, `test_results`, `deploy_log`, and `browser_qa_metadata`.

`browser_qa_metadata` is JSON-shape — every write routes through `yoke_core.domain.browser_qa_metadata.validate_json_string` so malformed payloads never reach the DB, and the canonical stored form is a compact sorted-key JSON object. Non-browser items hold the explicit negative-default object, not NULL.

Shepherd subagents (PM, Architect) write structured content during lifecycle transitions (e.g., spec, technical plan, shepherd log/caveats) using the same path.

### Error Propagation

| Step | Owner | Error Handling | Silent Failure Risk |
|------|-----------|---------------|---------------------|
| DB write | `items.structured_field.*` through the Yoke function-call dispatcher | Python prints to stderr and exits nonzero | **Low** — stderr propagates to caller |
| GitHub sync | `yoke_core.domain.backlog_github_sync` helpers | Returns nonzero on failure; sync failures are recorded in DB when invoked from backlog mutations | **Low** — failure is tracked and visible |
| Board rebuild | `yoke_core.domain.rebuild_board` via `yoke board rebuild` | Rebuild errors propagate to the caller | **Low** — rebuild failure is explicit |

### Project-Aware GitHub Sync

GitHub sync operations route through the Python-owned `yoke_core.domain.backlog_github_sync` helper family and service-client entrypoints. Repo and credential resolution flow through the canonical project-auth helper at `yoke_core.domain.project_github_auth.resolve_project_github_auth`, which returns a typed result envelope: the project's `owner/repo`, a short-lived bearer token, and a ready-to-thread subprocess env dict for callers that need one.

**One GitHub contract for Yoke and Buzz.** Both projects resolve through the same surface — Yoke is no longer a silent special case for "ambient default repo/auth." Project GitHub automation uses a GitHub App repo binding plus a short-lived App token. `projects.github_repo` remains the display/routing repo string during the cutover, but legacy project-secret rows are not a live GitHub auth storage shape.

There is no separate fallback chain: per-project token env-var lookup, project token-file lookup, and silent host-credential fallback are not part of the resolution path.

**Fail-closed on missing or broken auth.** When the resolver cannot produce a usable repo + App token (missing binding, missing installation, removed repo access, missing permission, private-key/config failure, or GitHub REST transport failure), it raises a typed diagnostic with a concrete `repair_command_hint`. Yoke-owned callers surface the diagnostic instead of silently falling through to host credentials or treating the remote as empty. Operators repair by connecting GitHub, adding repository access, binding the project repo, or switching the project to backlog-only. The runtime never instructs the operator to authenticate at the host CLI level as the answer to a project-auth/config problem.

**Cross-project coverage.** Item sync, status comments, issue close/reopen, body/title sync, resync repair, and doctor GitHub checks all route through the canonical resolver. Resync iterates per project; each iteration calls `resolve_project_github_auth(project)` and uses bearer-token REST calls for that project. Doctor's GitHub orphan and wrong-repo checks validate label coverage and confirm that each item's GitHub issue exists in the correct repo for its project.

**Per-project sync switch precedes auth.** A project with `projects.github_sync_mode='backlog_only'` never reaches the resolver: every sync helper skips it with one mode-language log line (return code 0, flows continue), and resync excludes it from fetch/classification/repair. The skip is policy, not an auth failure — a backlog-only project needs no GitHub authorization. See [github-sync.md](../github-sync.md).

### GitHub issue body size limit

GitHub rejects issue bodies above ~65,536 characters. Before calling GitHub's issue-body update endpoint, `items sync-body` and the shared body-update helper measure the rendered Yoke body against a conservative threshold (~62KB) defined in `yoke_core.domain.backlog_github_body_budget`. When the rendered body fits, full-body sync proceeds normally. When it exceeds the threshold, the helpers route to the **compact mirror** path instead.

**Compact mirror contents.** The compact mirror is the substitute body written to GitHub when the full rendered body is over budget. It contains item title, `YOK-N`, project, status, lifecycle state, an explicit note that the Yoke DB holds the canonical full body, key commands/links, and the latest evidence summary. The Yoke DB retains the full body — nothing is lost; the mirror just replaces what gets pushed to GitHub.

**Degradation reporting.** Compact-mirror sync is reported by the structured-write side-effect surface as `degraded_body_budget`, distinct from a successful full-body sync and distinct from an auth/config failure. Auth/config failures take precedence: if `resolve_project_github_auth` fails, no GitHub call is made and the surface reports the auth/config diagnostic, not a body-budget degradation.

**Unified across paths.** Issue create/reuse, lifecycle transitions, and structured-field side-effect syncs all use the same full-body vs compact-mirror contract — no path-specific drift.

**Backfill command.** Oversized-body backfill is an operator-maintenance repair for items already linked to GitHub issues whose rendered bodies exceed the budget. The repair identifies oversized rows, resyncs each one through the compact-mirror path, and is rerunnable on partial failure — previously-completed items are no-ops because they already match the compact-mirror state. It does not emit noisy comment chunking; one compact body per linked issue.

### Canonical Write Pattern

All agents should use structured field writes. Do not call lower-level item helpers directly, do not edit `.md` files and hope the content propagates. Raw body writes and `ingest-body` are no longer supported.
