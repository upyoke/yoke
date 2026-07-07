# Service Migration — YOK-1112 + YOK-1133 + YOK-1246 + YOK-1281

What moved into the Python domain layer, what still lives in shell today, and which follow-on tickets own collapsing the remaining shell authority.

## Overview

YOK-1112 extracted correctness-critical control-plane **read** logic from scattered endpoint code and shell scripts into a shared Python domain layer (`yoke/api/domain/`). The API and CLI now share one truth contract for lifecycle, approval, deployment-run, query, and board semantics.

YOK-1133 extended that shared ownership to the **write** surface: item create, update, and approval-apply mutations. Both API and shell now use one mutation contract for the supported control-plane fields, while shell still carries several side effects and unsupported-field paths as a transitional cutover line.

YOK-1281 shrunk `backlog-registry.sh` further into a thin side-effect adapter: create-time status validation and the update-field supported/unsupported dispatch whitelist now live exclusively in the Python mutation contract. `_apply_field_update` is Python-first — it calls `service-client.sh update-item` for **any** field and only falls back to shell for explicit `UNSUPPORTED_FIELD` responses. Shell-local rework detection was removed; rework flows only through mutation events.

YOK-1246 moved the process-heavy engine and domain logic into Python: the `yoke-db.sh epic`, `yoke-db.sh events`, `yoke-db.sh runs`, and `yoke-db.sh qa` routes now dispatch directly into Python modules; `merge-audit.sh` was fully deleted (replaced by `yoke/api/engines/merge_audit.py`); `doctor.sh` and `backlog-resync.sh` became thin launchers over Python engines (`yoke/api/engines/doctor`, `yoke/api/engines/resync`); and `observe-tool.sh` now defers attribution logic to `yoke/api/domain/observe.py`. The heavyweight shell test suites for the migrated 1246 surfaces were also moved to pytest; unrelated shell-native suites remain in place.

This document describes the current migration boundary, not the intended steady-state architecture. Follow-on backlog now makes the end state explicit:

- `YOK-1188` owns collapse of residual shell control-plane authority in routing, query classification, and semantic helper surfaces.
- `YOK-1279` owns Python-first write surfaces, side effects, and residual shell authority on the write path.

`YOK-1245` is the performance precedent for this direction: the board rebuild hot path moved behind a Python renderer while keeping `rebuild-board.sh` as the public shell entrypoint. Its measured shell baseline was about `16.4s-16.8s`, with a one-shot Python renderer expected to bring that path down to roughly `1.2s-1.5s`.

## What Lives in the Python Domain Layer

The following concerns are now owned by `yoke/api/domain/` and are the single source of truth for both API endpoints and CLI adapter commands.

### Lifecycle (`domain/lifecycle.py`)

| Concern | Before | After |
|---------|--------|-------|
| Status enum (item + task) | Inline string lists in `main.py` + shell lifecycle helpers | `ItemStatus` and `TaskStatus` enums |
| Delivery progression order | Scattered across shell registry and API code | `DELIVERY_PROGRESSION` tuple |
| Board column order | Duplicated in `main.py` and `rebuild-board.sh` | `BOARD_COLUMN_ORDER` tuple |
| Terminal/exceptional sets | Re-derived in multiple locations | `TERMINAL`, `TERMINAL_SUCCESS`, `TERMINAL_FAILURE`, `EXCEPTIONAL` frozen sets |
| Status validation | Not consistently enforced | `is_valid_item_status()`, `is_valid_task_status()` |
| Forward-transition check | Not available as a reusable function | `is_forward_transition()` |
| SQL fragment helpers | Inline in shell scripts | `sql_terminal_list()`, `sql_terminal_success_list()`, etc. |

### Approval (`domain/approval.py`)

| Concern | Before | After |
|---------|--------|-------|
| Halt-state vocabulary | Inline in `main.py` approve endpoint | `HaltState` enum + `HALT_RESOLUTION` map |
| Approval actions | Inline in endpoint | `ApprovalAction` enum |
| Stage authority field | String literal in multiple places | `STAGE_AUTHORITY_FIELD`, `STAGE_CACHE_FIELD` constants |
| Flow-stage parsing | Inline JSON parsing in endpoint | `parse_flow_stages()`, `FlowStage` dataclass |
| Approval resolution | Inline endpoint logic | `resolve_approval()` returns `ApprovalResolution` |

### Deployment Runs (`domain/runs.py`)

| Concern | Before | After |
|---------|--------|-------|
| Run status enum | CHECK constraint only | `RunStatus` enum + validation |
| Active/terminal classification | Inline in endpoint | `ACTIVE_RUN_STATUSES`, `TERMINAL_RUN_STATUSES` |
| Active-run lookup | Inline SQL + loop in endpoint | `find_active_run_for_item()` |
| Stage advancement | Inline endpoint logic | `advance_run_stage()` returns `StageAdvancement` |
| SQL fragment helpers | Inline | `sql_active_run_statuses()`, `sql_active_run_exists_for_item()` |

### Queries (`domain/queries.py`)

| Concern | Before | After |
|---------|--------|-------|
| Frozen semantics | Independently implemented in shell and API | `is_frozen()`, `sql_frozen_filter()` |
| Item filter model | Ad-hoc query construction | `ItemFilter` dataclass + `build_where_clause()` |
| Active queue definition | Implicit knowledge in operator prompts | `active_queue_filter()` |
| Pending work definition | Not formalized | `pending_work_filter()` |
| Item classification | Inline case statements | `classify_item_state()` |

### Board (`domain/board.py`)

| Concern | Before | After |
|---------|--------|-------|
| Status-to-bucket mapping | Duplicated in `rebuild-board.sh` and API | `status_to_board_bucket()` |
| Frozen bucket handling | Inline in board endpoint | Part of `status_to_board_bucket()` |
| Active-run upgrade (implemented->release) | Inline in board | Part of `status_to_board_bucket()` |
| Board projection | Inline in board endpoint | `project_board()` returns `BoardProjection` |
| Board stats | Inline computation | `BoardStats` dataclass |

### Mutations (`domain/mutations.py`) — YOK-1133

| Concern | Before | After |
|---------|--------|-------|
| Create validation | `backlog-registry.sh cmd_add` inline checks | `prepare_create()` returns `CreateResult` (YOK-1281: now includes status override validation) |
| Update validation | `backlog-registry.sh _apply_field_update` inline checks | `prepare_update()` returns `MutationResult` (YOK-1281: `_apply_field_update` is now Python-first — no shell-side supported-field whitelist) |
| Approval write application | Inline in `main.py` approve endpoint | `prepare_approval()` returns `ApprovalResult` |
| Title length limit | 200 in API, 100 in shell — inconsistent | `TITLE_MAX_LENGTH = 100` (authoritative) |
| Rework detection | `_apply_field_update` inline logic | Atomic in `prepare_update()` field_writes |
| Done cleanup | `_apply_field_update` inline logic | `DONE_CLEANUP_FIELDS` applied by `prepare_update()` |
| QA gates (YOK-833) | `_apply_field_update` inline SQL queries | `GateContext` pre-loaded, checked in `prepare_update()` |
| Epic task existence gate (YOK-588) | `_apply_field_update` inline SQL | `GateContext.epic_task_count` |
| Epic merge gate (YOK-781) | `_apply_field_update` inline check | `GateContext.has_merged_at` |
| Done-ceremony nonce (YOK-950) | Shell-owned filesystem check | Shell verifies nonce, sets `GateContext.done_nonce_verified` |
| Project/flow cross-validation | Scattered across shell and API | `prepare_create()` and `prepare_update()` |
| Deployed-to env validation (YOK-1131) | Not consistently enforced | `GateContext.valid_deploy_envs` |

#### Supported Mutation Surface

- **Create:** `title`, `type`, `priority`, `project`, `deployment_flow`, optional `status` override (type-aware validated, default=`idea` — YOK-1281)
- **Update:** `status`, `frozen`, `priority`, `project`, `deployment_flow`, `deployed_to`, `title`
- **Approval apply:** advance authoritative deployment-run stage + mirrored item stage, keep item at `status=release`

#### Unsupported Fields (Explicit Shell Fallback Today)

The following fields remain on explicit shell fallback paths today and are intentionally excluded from the shared mutation surface in `YOK-1133`:

| Field | Owner | Why |
|-------|-------|-----|
| `body` | `render-body.sh` (renderer-owned) | `_body_write_full()` removed in YOK-1323; body is a rendered projection |
| `source` | `backlog-registry.sh cmd_add` | Set at creation time, not user-mutable |
| `type` (update) | Shell only | Immutable after creation |
| `github_issue` | `sync-helper.sh` | GitHub sync side effect |
| `worktree` | `advance/` SKILL.md | Worktree lifecycle management |
| `merged_at` | `merge/SKILL.md` | Merge ceremony side effect |
| `flow` | `backlog-registry.sh` | Legacy field, rarely changed |
| `created_at` | Immutable | Set at creation |
| `rework_count` (direct) | Mutation layer | Atomically incremented during status transitions only |

This table is a transitional boundary, not a permanent one. `YOK-1279` now owns retiring or explicitly justifying these fallback paths so shell stops acting as a second write/control plane.

#### Service Client Write Commands — YOK-1133

| CLI Command | Domain Function | Used By |
|-------------|----------------|---------|
| `create-item --title T --type T [--priority P] [--project P] [--deployment-flow F] [--status S]` | `mutations.prepare_create()` | `backlog-registry.sh cmd_add` |
| `update-item <id> --field F --value V [--done-nonce-verified] [--force] [--qa-bypass]` | `mutations.prepare_update()` | `backlog-registry.sh _apply_field_update` |
| `apply-approval <id>` | `mutations.prepare_approval()` | `approve/SKILL.md` |

## What Remains Shell Adapter Logic

These are the current shell-owned adapter/executor responsibilities. They are not all presumed permanent. Where the behavior is correctness-critical, performance-sensitive, or semantically duplicated, the expectation is to collapse it behind Python-owned surfaces over time.

Shell scripts remain the correct adapter/executor layer for concerns that are inherently environment-local or require OS-level tool orchestration.

### Git and Worktree Operations

- `advance/` SKILL.md phases: worktree creation, branch management
- `merge/SKILL.md`: PR merges, branch cleanup
- `usher/SKILL.md`: post-merge pipeline orchestration
- All git operations (commit, push, checkout) remain shell

### Filesystem Mutation

- `generate-backlog-md.sh`: `.md` file regeneration from DB
- `rebuild-board.sh`: `BOARD.md` generation shell entrypoint (handles throttling, locking, file I/O; delegates rendering to `python3 -m runtime.api.board`)
- `backup-db.sh`: SQLite backup management
- File writes, temp file management, cleanup traps

### GitHub CLI Integration

- `sync-helper.sh`: GitHub issue sync with per-project token isolation
- `gh-issue.sh`: GitHub issue number resolution
- `github-actions.sh`: GitHub Actions trigger and polling
- All `gh` CLI invocations

### Browser Orchestration

- `browser-daemon.sh`: Playwright daemon lifecycle
- `browser-snapshot.sh`: screenshot + accessibility + diff
- `browser-exec.sh`: step execution
- All Node.js subprocess management

### Event Emission and Telemetry

- `emit-event.sh`: structured event emitter
- `observe-tool.sh`: PostToolUse/PostToolUseFailure hooks
- `populate_registry.py`: event registry management

### Subprocess Orchestration

- `deploy-pipeline.sh`: stage iteration, executor dispatch, resume (**explicitly out of scope for YOK-1133**)
- `update-status.sh`: epic-task status mutation shell orchestration (calls `yoke-db.sh epic` which now delegates to Python)
- Complex multi-step shell workflows

### DB Write Orchestration

- `backlog-registry.sh` structured field writes via `_render_and_sync()`: DB write + body render + `.md` regen + GitHub sync (`_body_write_full()` removed in YOK-1323)
- `yoke-db.sh`: unified DB router for all shell access
- Domain-specific DB routes: `yoke-db.sh epic`, `yoke-db.sh events`, `yoke-db.sh runs`, and `yoke-db.sh qa` now dispatch directly to Python domain modules (YOK-1246). The standalone compatibility wrapper files were transitional cargo and are removed on this branch. `project-db.sh`, `flow-db.sh`, `ouroboros-db.sh`, `shepherd-db.sh`, and others remain shell-native.

### Shell-Owned Side Effects (preserved by YOK-1133 cutover)

After `backlog-registry.sh` delegates validation/semantics to the service client, it still owns:

- Board rebuilds (`rebuild-board.sh`)
- `.md` file regeneration (`generate-backlog-md.sh`)
- GitHub issue sync (`sync-helper.sh`)
- GitHub issue close on done
- Telemetry emission (`emit-event.sh`)
- Git operations (worktree create/cleanup)

These ownership lines are current-state facts, not end-state commitments. YOK-1246 completed the engine migration slice; `YOK-1279` explicitly tracks shrinking the remaining write-side surface.

## What Runtime-Specific Behavior Remains Out of Scope

The following are intentionally NOT migrated in this epic. They remain environment-specific or would require broader infrastructure changes.

### Hook System

- `PreToolUse` / `PostToolUse` hooks (`lint-sqlite-cmd.sh`, `observe-tool.sh`, etc.)
- These are Claude Code runtime-specific and do not apply to API or deployed service
- Enforcement logic that hooks provide is separately covered by domain-layer validation

### Session and Prompt Behavior

- `harness-session-start.sh` orientation injection
- SKILL.md prompt-shaped behavior (conduct, shepherd, etc.)
- Agent dispatch and subagent orchestration
- These are inherently Claude Code session concerns

### Board Rendering (Art + Dashboard + Sections)

Board rendering has been migrated to Python in the `yoke/api/board/` package (YOK-1245). The normal `BOARD.md` rebuild path now delegates to `python3 -m runtime.api.board`, which handles art headers, dashboard widgets, board sections, and the project timelines widget. The domain-layer `board.py` owns data projection (status-to-bucket mapping, board stats); the `board/` package owns visual rendering.

The shell rendering helpers (`board-art-variants.sh`, `board-grid-engine.sh`, `zen-scene.sh`) were deleted in YOK-1339 — their logic is fully covered by `art.py` and `zen.py`. The standalone preview tool `preview-board-art.sh` is now a thin shell launcher that delegates to `python3 -m runtime.api.board preview`.

### Complex Gate Logic

- `qa-gate-check.sh`: QA transition guards that combine multiple shell-specific concerns
- `classify-browser-qa.sh`: browser-testable item classification
- These involve multi-tool integration that is best orchestrated in shell

## Service Client Bridge

The `service_client.py` CLI adapter bridges shell scripts into the Python domain layer. Shell scripts call it via the `service-client.sh` wrapper.

### Read/Decision Commands (YOK-1112)

| CLI Command | Domain Function | Used By |
|-------------|----------------|---------|
| `approve-check <flow> <stage>` | `approval.resolve_approval()` | Approval gates in deployment pipelines |
| `active-queue [--project P]` | `queries.active_queue_filter()` + `build_where_clause()` | Queue analysis |
| `classify-status <status>` | `board.status_to_board_bucket()` | Board rendering helpers |
| `validate-status <status>` | `lifecycle.is_valid_item_status()` | Status transition guards |
| `validate-transition <from> <to> [--item-type TYPE]` | `lifecycle.is_forward_transition(..., item_type=)` | Transition validation |

### Write/Mutation Commands (YOK-1133)

| CLI Command | Domain Function | Used By |
|-------------|----------------|---------|
| `create-item --title T --type T [...]` | `mutations.prepare_create()` | `backlog-registry.sh cmd_add` |
| `update-item <id> --field F --value V [...]` | `mutations.prepare_update()` | `backlog-registry.sh _apply_field_update` |
| `apply-approval <id>` | `mutations.prepare_approval()` | `approve/SKILL.md` |

## Package Structure

The domain layer and board renderer are importable as standard Python packages:

```
yoke/                     # Package root (__init__.py)
  api/                      # API package (__init__.py)
    domain/                 # Domain layer package (__init__.py)
      lifecycle.py          # Lifecycle statuses, progression, validation
      approval.py           # Halt states, approval resolution
      runs.py               # Deployment-run semantics
      queries.py            # Item filters, frozen semantics
      board.py              # Board projection, bucket mapping
      mutations.py          # Create/update/approve mutation semantics (YOK-1133)
      epic.py               # Epic task CRUD (YOK-1246) — replaces yoke-db.sh epic logic
      events_crud.py        # Events/registry CRUD (YOK-1246) — replaces yoke-db.sh events logic
      deployment_runs.py    # Deployment run CRUD (YOK-1246) — replaces yoke-db.sh runs logic
      qa.py                 # QA platform CRUD (YOK-1246) — replaces yoke-db.sh qa logic
      observe.py            # Observe-tool telemetry (YOK-1246) — extracted from observe-tool.sh inline Python
    board/                  # Board renderer package (YOK-1245)
      __init__.py
      __main__.py           # CLI: python3 -m runtime.api.board (render + preview)
      art.py                # Art config, master map, header rendering
      config.py             # Board config parser (yoke/config)
      db.py                 # SQLite queries (items, epic_tasks, velocity)
      renderer.py           # Top-level assembly (art + widgets + sections + zen)
      sections.py           # Board sections, classification, epic sub-rows
      widgets.py            # Dashboard widgets (velocity, WIP, weather, etc.)
      zen.py                # Project timelines widget
    engines/                # Process-heavy engines (YOK-1246)
      __init__.py
      doctor.py             # Doctor health check engine — replaces doctor.sh logic
      resync.py             # Backlog resync engine — replaces backlog-resync.sh logic
      merge_audit.py        # Merge audit engine — replaces merge-audit.sh (deleted)
    main.py                 # FastAPI endpoints (HTTP concerns only)
    service_client.py       # CLI adapter for shell access (read + write commands)
    start-api.sh            # Startup script (uses runtime.api.main:app)
    restart-api.sh          # Restart script
```

### Local Development

```bash
# From repo root — no install needed, Python resolves yoke/ as a package:
python3 -m pytest yoke/api/ -v

# Or install in editable mode for IDE support:
pip install -e .
```

### Deployed Infrastructure

The `pyproject.toml` defines the package metadata and dependencies. For deployed environments:

```bash
pip install .
# Or in a container:
pip install /app
uvicorn runtime.api.main:app --host 0.0.0.0 --port 8765
```

The same domain code runs in both contexts. The `YOKE_DB` environment variable controls the database path.

## Migration Completeness

### Correctness-Critical Logic in Python (Complete)

- Lifecycle status validation and progression
- Approval halt-state resolution
- Deployment-run active/terminal classification
- Item query filtering (frozen, done, cancelled exclusions)
- Board bucket classification
- Board stats projection
- Item create validation (title, type, priority, project/flow cross-check) — YOK-1133
- Item update validation (supported field subset, transition gates, rework, done cleanup, QA gates) — YOK-1133
- Approval write application (stage advancement, member sync, run advancement) — YOK-1133

### Remaining Raw SQLite in Shell (Adapter Uses)

Shell scripts that still use direct `sqlite3` (via `yoke-db.sh query`) for:

- Item body rendering (`render-body.sh`; raw body writes via `_body_write_full()` removed in YOK-1323)
- Epic task management (create, update, progress notes)
- Event emission and telemetry logging
- Deployment-run creation and DB writes
- Unsupported field updates (see "Unsupported Fields" table above)
- Shell-native DB wrappers: `project-db.sh`, `flow-db.sh`, `ouroboros-db.sh`, `shepherd-db.sh`, `release-notes-db.sh`, `designs-db.sh`, `env-db.sh`, `schema-db.sh`, `harness-sessions-db.sh`

After YOK-1133, YOK-1246, YOK-1281, YOK-1323, and YOK-1383: item create/update/approve validation and semantics flow through the Python domain layer. `backlog-registry.sh` is now a transitional side-effect adapter: it calls the Python mutation layer for all supported fields, applies returned `field_writes` via SQLite, and owns only the remaining external side effects. Raw body writes are removed; `items.body` is a virtual rendered field (not stored in DB). Epic task CRUD, events/registry, deployment runs, and QA operations all delegate to Python domain modules (YOK-1246). The doctor engine, backlog resync, and merge audit are Python engines (YOK-1246).

This remaining raw-SQLite shell layer is now explicit backlog to shrink, not a design destination. `YOK-1279` targets the write-side ownership boundary.

## Python-Authoritative Domain Modules with Shell Adapters

The Python domain layer is the authoritative source of truth. Shell scripts are compatibility adapters that delegate to or are generated from the Python modules:

| Python Module (authoritative) | CLI Surface | Validated By |
|-------------------------------|-------------|-------------|
| `lifecycle.py` | *(Python-only; no shell adapter)* | `HC-api-vocabulary-drift` doctor check, `test_domain.py` |
| `approval.py` | `approval-vocabulary.sh` | `test_domain.py` shell-parity tests |
| `board.py` | `rebuild-board.sh` | `test_parity.py` bucket classification tests |
| `queries.py` | `query-items.sh` | `test_parity.py` active-queue parity tests |
| `runs.py` | `yoke-db.sh runs` | `test_parity.py` run advancement tests |
| `mutations.py` | `backlog-registry.sh` | `test_parity.py` write parity tests, `test_mutations.py` |
| `epic.py` | `yoke-db.sh epic` | `test_epic_full.py` |
| `events_crud.py` | `yoke-db.sh events` | `test_events_crud_full.py` |
| `deployment_runs.py` | `yoke-db.sh runs` | `test_deployment_runs_full.py` |
| `qa.py` | `yoke-db.sh qa` | `test_qa_full.py` |
| `observe.py` | `observe-tool.sh` (inline import) | `test_observe_full.py` |
| `engines/doctor.py` | `doctor.sh` (thin launcher) | `test_doctor_*.py` |
| `engines/resync.py` | `backlog-resync.sh` (thin launcher) | `test_resync_full.py` |
| `engines/merge_audit.py` | *(deleted)* | `test_merge_audit_full.py` |

Shell adapters exist for backward compatibility with shell callers. After YOK-1246, the remaining shell-native DB wrappers are: `project-db.sh`, `flow-db.sh`, `ouroboros-db.sh`, `shepherd-db.sh`, `release-notes-db.sh`, `designs-db.sh`, `env-db.sh`, `schema-db.sh`, `harness-sessions-db.sh`. `YOK-1188` and `YOK-1279` own narrowing these remaining shell surfaces.

The `HC-api-vocabulary-drift` doctor check and the parity suites validate alignment at health-check/test time.

## Explicitly Out of Scope

The following systems were intentionally excluded from the `YOK-1112` / `YOK-1133` migration slice. That does not mean they are permanent shell architecture boundaries; it means they require follow-on tickets to retire or narrow them safely.

### `deploy-pipeline.sh` — Deployment Pipeline Orchestration

`deploy-pipeline.sh` owns executor-heavy stage iteration, resume, retry, and failure semantics. It orchestrates GitHub Actions workflows, SSH deployments, and environment promotion. This remained out of scope for `YOK-1133`, but it is explicit follow-on backlog rather than a permanent shell-only zone.

### `update-status.sh` / `yoke-db.sh epic` — Epic-Task Mutation

Epic-task status mutation (individual task advancement within an epic) is a separate workflow-task surface. `yoke-db.sh epic` now delegates to `runtime.api.domain.epic` (YOK-1246 task 006) — all CRUD logic for `epic_tasks`, `epic_task_files`, `epic_dispatch_chains`, and `epic_progress_notes` lives in Python. `update-status.sh` remains the shell orchestration layer for status transitions (event emission, board rebuilds, GitHub label sync).

### Body and Structured-Field Writes

`_body_write_full()` was removed in YOK-1323. `items.body` is now a virtual rendered field (YOK-1383) — not stored in the DB, rendered on demand by `render_body.py`. All content goes through structured field writes, which trigger `_render_and_sync()` for GitHub sync. The Python-first direction for structured writes continues under `YOK-1279`.

### Generic Write Support

The mutation layer covers the supported control-plane field subset. Fields outside that surface (`type`, `epic`, `source`, `deploy_stage`) remain on explicit shell fallback paths today via `_apply_field_update_shell_fallback()`, triggered only when the Python layer returns `UNSUPPORTED_FIELD`. These fallback paths are backlog to retire or explicitly justify rather than a statement that generic write support should stay shell-owned forever.

## YOK-1246 Through Wave 3 — Final Migration State

YOK-1246 started the process-heavy engine migration. Wave 2 and Wave 3 completed the literal zero-shell closeout. No tracked `.sh` files remain in the repo.

### Canonical Python Entry Surfaces

| Former shell surface | Canonical Python surface | Final state |
|----------------------|--------------------------|-------------|
| DB router / wrapper family | `python3 -m runtime.api.cli.db_router` | All DB and query entrypoints route through Python |
| Public backlog mutation CLI | `python3 -m runtime.api.service_client backlog-cli` | Backlog add/update/close flows are Python-owned |
| Epic task CLI | `python3 -m runtime.api.domain.epic` | Epic-task CRUD and status transitions are Python-owned |
| Doctor / resync / done-transition / repair-status | `python3 -m runtime.api.engines.<name>` | Engine launchers are Python-owned |
| Hook and session entrypoints | git-root-stable `env PYTHONPATH="$(git rev-parse --show-toplevel)${PYTHONPATH:+:$PYTHONPATH}" python3 -m runtime.harness.codex.codex_hooks ...`, plus `python3 -m runtime.harness.session_hooks ...` | Hook execution is Python-owned |
| Harness bootstrap | `python3 -m runtime.harness.codex.codex_entry bootstrap` | Wrapper bootstrap is Python-owned |
| API lifecycle | `python3 -m runtime.api.tools.api_server {start,restart,stop}` | API server lifecycle is Python-owned |
| Install / test runner | `python3 -m runtime.api.tools.yoke_install`, `python3 -m runtime.api.tools.run_tests` | Install and test entrypoints are Python-owned |

### What Was Deleted

- The `yoke-db.sh` compatibility family and all remaining wrapper scripts
- Shell-native hook launchers, harness launchers, and test harness files
- Shell runner entrypoints for install, API lifecycle, board preview, and test execution
- Tracked external shell artifacts in templates and projects

### What Remains

- No tracked `.sh` files remain in the repo.
- External projects may still emit shell at render or deploy time, but that output is generated from Python-owned or template-owned source, not tracked here.
