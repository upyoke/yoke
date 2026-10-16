# Generated task model

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Items](../index.md) > Generated task model
<!-- /yoke:breadcrumbs -->

Read the generated task graph, dispatch chains and durable progress records.

## Table: epic_tasks

```sql
id INTEGER PRIMARY KEY
epic_id INTEGER NOT NULL
task_num INTEGER NOT NULL
title TEXT -- length capped by the parent item's project title policy
item_worktree_id INTEGER -- registered lane identity
context_estimate TEXT -- S|M|L|XL
dependencies TEXT -- comma-separated task nums
status TEXT DEFAULT 'planning' CHECK(status IN ('planning','plan-drafted','refining-plan','planned','implementing','reviewing-implementation','reviewed-implementation','polishing-implementation','implemented','release','done','failed','blocked','stopped'))
dispatch_attempts INTEGER DEFAULT 0
body TEXT
github_issue TEXT
scope_state TEXT NOT NULL DEFAULT 'pending' -- pending|paths|no_files|legacy_deferred
scope_finalized_at TEXT
max_attempts INTEGER DEFAULT 5
agent_id TEXT
last_heartbeat TIMESTAMPTZ
last_activity_at TIMESTAMPTZ
UNIQUE(epic_id, task_num)
```

## Table: epic_task_files

```sql
id INTEGER PRIMARY KEY
epic_id INTEGER NOT NULL
task_num INTEGER NOT NULL
file_path TEXT NOT NULL
action TEXT -- create|modify|delete
UNIQUE(epic_id, task_num, file_path)
FOREIGN KEY (epic_id, task_num) REFERENCES epic_tasks(epic_id, task_num)
```

## Table: epic_dispatch_chains

```sql
id INTEGER PRIMARY KEY
epic_id INTEGER NOT NULL
item_worktree_id INTEGER -- registered lane identity
queue TEXT -- JSON array of task nums
current_index INTEGER DEFAULT 0
current_task TEXT
current_attempt INTEGER DEFAULT 1
max_attempts INTEGER DEFAULT 5
no_chain INTEGER DEFAULT 0
started_at TIMESTAMPTZ
last_updated TIMESTAMPTZ
UNIQUE(epic_id, item_worktree_id)
```

## View: item_progress_view

Read model for item delivery progress. Joins `items`, `deployment_flows`, and (when present) `deployment_runs` / `deployment_run_items` to project a single-row progress summary per item. Schema convergence owns its construction.

```sql
-- Fields returned per item:
item_id INTEGER -- items.id
status TEXT -- current item status
flow_name TEXT -- deployment_flows.name (NULL if no flow assigned)
run_id TEXT -- deployment_runs.id (NULL if no active run or table missing)
current_stage TEXT -- deployment_runs.current_stage (NULL if no run)
target_environment TEXT -- resolved environment name, else the flow's target_tier (NULL if not set)
stage_progress TEXT -- 'N/M' format (NULL if no run)
done_description TEXT -- deployment_flows.done_description (NULL if no flow)
qa_summary TEXT -- latest QA run result summary (NULL if none)
blocked_reason TEXT -- blocking condition description (NULL if not blocked)
```

**Graceful degradation:** When `deployment_runs` table does not exist, the view is created with NULL for all run-specific fields (run_id, current_stage, stage_progress, blocked_reason). Schema convergence uses Postgres introspection when constructing the view.

**Read through:** registered item progress/read surfaces; use the function catalog and `yoke items --help` for the served roster.

## Table: epic_progress_notes

```sql
id INTEGER PRIMARY KEY
epic_id INTEGER NOT NULL
task_num INTEGER NOT NULL
note_num INTEGER NOT NULL
body TEXT
commit_hash TEXT
synced_to_github INTEGER DEFAULT 0
created_at TIMESTAMPTZ NOT NULL
UNIQUE(epic_id, task_num, note_num)
```


## Related

- [Item model](items.md)
