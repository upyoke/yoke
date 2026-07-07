# Backlog Item Frontmatter Schema

Canonical schema for `backlog/{NNN}.md` YAML frontmatter. Used by `doctor.sh` HC-16 for validation.

## Required Fields

| Field | Type | Valid Values | Written By |
|-------|------|-------------|------------|
| `id` | string | `YOK-{N}` | `backlog-registry.sh add` |
| `title` | string | non-empty | `backlog-registry.sh add` |
| `type` | enum | `epic`, `issue` | `backlog-registry.sh add` |
| `status` | enum | see lifecycle below | `backlog-registry.sh update` |
| `priority` | enum | `high`, `medium`, `low` | `backlog-registry.sh add` |

## Optional Fields

| Field | Type | Default | Written By |
|-------|------|---------|------------|
| `flow` | enum | `accelerated` or `full` | `backlog-registry.sh add` (auto-detected from spec) |
| `rework_count` | integer | `0` | `backlog-registry.sh update` (auto-incremented on done/qa -> active) |
| `frozen` | boolean | `false` | `backlog-registry.sh update` |
| `sprint` | string or null | `null` | `backlog-registry.sh update` |
| `track` | string or null | `null` | `backlog-registry.sh update` |
| `track_seq` | positive integer or null | `null` | `backlog-registry.sh update` |
| `epic` | string or null | `null` | `plan` / `sync` SKILL.md (sets epic dir name) |
| `github_issue` | string or null | `null` | `backlog-registry.sh sync-item` (sets `#N`) |
| `deployed_to` | string or null | `null` | Auto-set from `deployment_flows.target_env` when pipeline completes (YOK-745). Manual override: `advance --env`. |
| `worktree` | string or null | `null` | `advance active` (sets branch name, e.g. `issue/YOK-{N}`) |
| `created` | ISO 8601 timestamp | auto | `backlog-registry.sh add` |
| `updated` | ISO 8601 timestamp | auto | `backlog-registry.sh update` / `yaml-helper.sh set` |
| `merged_at` | ISO 8601 timestamp or null | `null` | `merge` SKILL.md |
| `source` | string | `user` | `backlog-registry.sh add` (provenance: who/what created the item) |
| `project` | string | `yoke` | `backlog-registry.sh add` (FK to `projects.id`; which project this item targets) |
| `deployment_flow` | string or null | `null` | Usher / `advance` (FK to `deployment_flows.id`; assigned deployment flow) |
| `deploy_stage` | string or null | `null` | Usher (current stage in the deployment flow; see deploy_stage section below) |

## Sprint / Board Placement Fields

The fields `frozen`, `sprint`, `track`, and `track_seq` control how items are placed on the sprint board (`yoke/BOARD.md`). They are managed by `/yoke tracks` and sprint planning workflows. See the board layout documentation for how these fields map to board sections.

| Field | Board Effect |
|-------|-------------|
| `sprint` | Assigns item to a named sprint; unassigned items appear in the backlog section |
| `track` | Groups item into a parallel work track within the sprint |
| `track_seq` | Orders item within its track (lower numbers first) |
| `frozen` | When `true`, item is locked in place and cannot be reordered by automated processes |

### Done-Transition Cleanup (FR-10)

When an item's status is set to `done`, the following fields are automatically cleared:
- `track` -> `null`
- `track_seq` -> `null`
- `frozen` -> `false`

The `sprint` field is **retained** for historical attribution (which sprint completed the work).

## Deployment Pipeline Fields

The fields `project`, `deployment_flow`, and `deploy_stage` control the post-merge deployment pipeline. They are managed by the Usher skill.

| Field | Purpose |
|-------|---------|
| `project` | Which project this item targets (FK to `projects.id`). Defaults to `yoke`. Determines which deployment flows are available. |
| `deployment_flow` | Which deployment flow to use for this item (FK to `deployment_flows.id`). Set when the item enters the pipeline. NULL means no deployment needed. |
| `deploy_stage` | Current position within the deployment flow's stage sequence. NULL means not started. See `deploy_stage` values below. |

### deploy_stage Values

The `deploy_stage` field tracks progress through a deployment flow. It can hold:

- `NULL` -- item has not entered the deployment pipeline
- Any stage name from the flow's `stages` JSON array (e.g., `staging-deploy`, `smoke`, `prod-deploy`)
- `needs-capability` -- pipeline halted; a required infrastructure capability is missing or misconfigured
- `awaiting-approval` -- pipeline halted at a `human-approval` gate
- `complete` -- all stages executed successfully; item is ready to transition to `done`

The `deploy_stage` is distinct from `status`. An item at `status=merged` progresses through deploy stages without changing status until the pipeline completes, at which point the Usher transitions the item to `done`.

## Status Lifecycle

All items share a single 12-state lifecycle (type does not gate which statuses are available -- skipping states is allowed):

`idea` -> `defined` -> `designed` -> `planned` -> `ready` -> `active` -> `review` -> `merged` -> `qa` -> `passed` -> `done`

The `merged` status marks items that have been merged to the main branch but may still need deployment. The Usher skill manages the `merged` -> `done` transition, executing the item's deployment flow stages if one is assigned. Items without a deployment flow pass through to `done` directly.

`cancelled` is a terminal status that can be reached from any state. Like `done` and `merged`, it triggers GitHub issue closure and maps to expected state `CLOSED`.

## Valid Status Values

`idea`, `defined`, `designed`, `planned`, `ready`, `active`, `review`, `merged`, `qa`, `passed`, `done`, `cancelled`

Note: `needs-capability` and `awaiting-approval` are **deploy_stage values**, not item statuses. They represent halt states within the deployment pipeline while the item remains at `status=merged`.

## Validation Rules

1. All required fields must be present and non-empty
2. `type` must be `epic` or `issue`
3. `status` must be a valid lifecycle status (unified for all types)
4. `priority` must be `high`, `medium`, or `low`
5. `id` must match the filename: `backlog/065.md` -> `id: YOK-65`
6. `github_issue` if present must match `#N` format
7. `created` and `updated` must be valid ISO 8601 timestamps
8. No unknown fields -- any field not listed above indicates schema drift
9. `frozen` must be `true` or `false` (boolean)
10. `track_seq` must be a positive integer or `null`
11. `sprint` must be a non-empty string or `null`
12. `track` must be a non-empty string or `null`
13. `flow` must be `accelerated` or `full`
14. `rework_count` must be a non-negative integer
15. `source` must be a non-empty string (e.g., `user`, `tester`, `curate`)
16. `project` must be a valid project ID (FK to `projects.id`); defaults to `yoke`
17. `deployment_flow` if present must be a valid deployment flow ID (FK to `deployment_flows.id`)
18. `deploy_stage` if present must be a valid stage name, `needs-capability`, `awaiting-approval`, or `complete`

## SQLite Schema (`items` table)

The `items` table in `yoke/yoke.db` is the **write-path source of truth** for all backlog item data. All CRUD operations (`backlog-registry.sh add`, `update`, `sync-item`, etc.) write to the DB via `item-db.sh`. After each write, `generate-backlog-md.sh` regenerates the corresponding `.md` file, ensuring `.md` files are always consistent generated views of the DB state. The `.md` files are never written to directly for field mutations — they exist for human readability and for read-path consumers that parse YAML frontmatter (e.g., `rebuild-board.sh`, `advance` SKILL.md).

### Table Definition

```sql
CREATE TABLE IF NOT EXISTS items (
  id            INTEGER PRIMARY KEY,
  title         TEXT    NOT NULL,
  type          TEXT    NOT NULL DEFAULT 'issue',
  status        TEXT    NOT NULL DEFAULT 'idea',
  priority      TEXT    NOT NULL DEFAULT 'medium',
  flow          TEXT,
  rework_count  INTEGER,
  frozen        INTEGER,
  sprint        TEXT,
  track         TEXT,
  track_seq     INTEGER,
  epic          TEXT,
  github_issue  TEXT,
  deployed_to   TEXT,
  worktree      TEXT,
  body          TEXT,
  merged_at     TEXT,
  created_at    TEXT    NOT NULL,
  updated_at    TEXT    NOT NULL,
  source        TEXT    NOT NULL DEFAULT 'user',
  project       TEXT    DEFAULT 'yoke',       -- FK -> projects(id)
  deployment_flow TEXT,                         -- FK -> deployment_flows(id)
  deploy_stage  TEXT                            -- current stage in deployment flow
);
```

### Field Mapping: Frontmatter to DB

| Frontmatter Field | DB Column | Mapping Notes |
|---|---|---|
| `id: YOK-42` | `id: 42` | Strip `YOK-` prefix, store as integer |
| `created` | `created_at` | Renamed for SQL convention |
| `updated` | `updated_at` | Renamed for SQL convention |
| `frozen: true` | `frozen: 1` | Boolean to integer (true->1, false->0, absent->NULL) |
| `frozen: false` | `frozen: 0` | Boolean to integer |
| `rework_count: 3` | `rework_count: 3` | Stored as integer |
| `track_seq: 2` | `track_seq: 2` | Stored as integer |
| `field: null` | `field: NULL` | YAML null maps to SQL NULL |
| (field absent) | `field: NULL` | Missing fields map to SQL NULL |
| `project` | `project` | Direct mapping (string FK) |
| `deployment_flow` | `deployment_flow` | Direct mapping (string FK) |
| `deploy_stage` | `deploy_stage` | Direct mapping (string, nullable) |
| body (below `---`) | `body` | Full markdown body text |

### Canonical Frontmatter Field Order

When generating .md files from the DB (`generate-backlog-md.sh`), fields are always emitted in this order:

1. `id`, `title`, `type`, `status`, `priority`, `flow`
2. `rework_count`, `frozen`, `sprint`, `track`, `track_seq`
3. `epic`, `github_issue`, `deployed_to`, `worktree`
4. `project`, `deployment_flow`, `deploy_stage` (only when non-default/non-NULL)
5. `created`, `updated`, `source`
6. `merged_at` (only when non-NULL)

**Item-level dependencies** are stored in the `item_dependencies` table (not in the items table). See `yoke/docs/db-reference.md` for the `item_dependencies` schema. Dependencies with `dependency_type = 'hard-block'` block dispatch until the blocking item reaches `done`.

This canonical order ensures round-trip fidelity: `migrate-to-sqlite.sh` followed by `generate-backlog-md.sh` produces byte-identical output for normalized files.
