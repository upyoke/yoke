"""``project`` topic delivery-lane table entries for the schema cheat sheet.

Sibling of :mod:`schema_api_context_tables` (which combines per-topic
dicts into the canonical ``CANONICAL_TABLES``). Holds deployment_flows,
deployment_runs, deployment_run_items, ephemeral_environments.

Pure data only — no I/O or DB connections.
"""

from __future__ import annotations


DELIVERY_TABLES: dict[str, dict] = {
    "deployment_flows": {
        "columns": [
            ("id", "TEXT"),
            ("project_id", "INTEGER"),
            ("name", "TEXT"),
            ("description", "TEXT"),
            ("stages", "TEXT"),
            ("on_failure", "TEXT"),
            ("created_at", "TEXT"),
            ("target_tier", "TEXT"),
            ("target_environment_id", "INTEGER"),
            ("done_description", "TEXT"),
            ("status", "TEXT"),
        ],
        "notes": (
            "Deployment-flow definitions keyed by TEXT `id`. Project "
            "lookup uses numeric `project_id`; join projects for the slug. "
            "The human flow name is `name`. `status` is `active` or "
            "`disabled`; disabled definitions remain readable for historical "
            "runs but cannot be assigned or start new runs. `target_tier` "
            "is `persistent` (with `target_environment_id` referencing "
            "`environments.id` — JOIN environments for the display name), "
            "`ephemeral` (per-run preview substrate), or NULL (merge-only); "
            "there is no `target_env` label column (stale guess). "
            "`stages` is a JSON-array column whose elements define the "
            "ordered pipeline steps. A `human-approval` stage names who "
            "may approve with `approvals: {roles, actors}` — the same "
            "address shape as workflow `policies.approval_defaults` "
            "(roles `owner`/`operator`/`admin`, optional named actor "
            "ids). Operator create/update refuses a human-approval "
            "stage that omits that address. Canonical lookup: `SELECT "
            "id, stages FROM deployment_flows WHERE id = ?;` then "
            "`json.loads(stages)` to walk the stage list."
        ),
    },
    "deployment_runs": {
        "columns": [
            ("id", "TEXT"),
            ("project_id", "INTEGER"),
            ("flow", "TEXT"),
            ("target_tier", "TEXT"),
            ("target_environment_id", "INTEGER"),
            ("release_lineage", "TEXT"),
            ("status", "TEXT"),
            ("current_stage", "TEXT"),
            ("created_at", "TEXT"),
            ("started_at", "TEXT"),
            ("completed_at", "TEXT"),
            ("created_by", "TEXT"),
            ("carried_work", "TEXT"),
        ],
        "notes": (
            "One row per deployment-flow execution. Primary key is the "
            "TEXT `id` (run identifier like 'run-YYYYMMDD-NNN'); the "
            "`flow` column joins to `deployment_flows.id`. There is no "
            "`item_id` column on this table. Item-bound delivery joins "
            "through `deployment_run_items`. Use `deployment_runs.id` in "
            "raw run queries; do not look for a `run_id` column on the run "
            "table (that column lives on `deployment_run_items`). Normal "
            "hosted releases are "
            "item-bound; zero-member runs are reserved for explicit "
            "environment administration and still advance this run row. To "
            "read what any succeeded run actually shipped, inspect the "
            "`carried_work` JSON object: `items` are attribution matches, "
            "`commits` are unresolved bare SHAs, and `derivation.reason` "
            "names an explicit empty result. It is independent of member "
            "lifecycle. To "
            "approve an executing run whose current flow stage uses the "
            "`human-approval` executor, use `yoke deployment-runs approve "
            "RUN-ID [--note TEXT]`; the run stage is authoritative and Yoke "
            "synchronizes member item stage caches atomically. To "
            "find the active deploy run for an item, JOIN through "
            "`deployment_run_items`: `SELECT dr.id, dr.status, "
            "dr.current_stage, dr.target_environment_id FROM deployment_runs dr "
            "JOIN deployment_run_items dri ON dri.run_id = dr.id WHERE "
            "dri.item_id = ? ORDER BY dr.created_at DESC LIMIT 1;`. "
            "Stale-run HCs scan rows where `status` is non-terminal "
            "but `started_at` is older than the configured cutoff; "
            "item-less is suspicious only when a run never starts."
            " New run creation locks `deployment_runs` in Postgres, computes "
            "the UTC day's maximum numeric suffix plus one, and inserts under "
            "the same transaction with the primary key as a collision guard. "
            "`runs next-id` is only a non-reserving preview."
        ),
    },
    "deployment_run_items": {
        "columns": [
            ("run_id", "TEXT"),
            ("item_id", "INTEGER"),
            ("added_at", "TEXT"),
        ],
        "notes": (
            "Many-to-many linkage between deployment_runs and items. "
            "Composite primary key is `(run_id, item_id)`. Canonical "
            "JOINs: `dri.run_id = dr.id` reaches the parent run, "
            "`dri.item_id = items.id` reaches the linked item. See the "
            "deployment_runs entry above for the full active-run "
            "query. Do not require a row here for environment-level "
            "deploy runs; zero rows means no attached backlog item, not "
            "a broken run once `deployment_runs.status` has moved past "
            "`created`."
        ),
    },
    "ephemeral_environments": {
        "columns": [
            ("id", "INTEGER"),
            ("project_id", "INTEGER"),
            ("branch", "TEXT"),
            ("item", "TEXT"),
            ("workflow_run_id", "TEXT"),
            ("github_ref", "TEXT"),
            ("port_api", "INTEGER"),
            ("port_web", "INTEGER"),
            ("url", "TEXT"),
            ("status", "TEXT"),
            ("started_at", "TEXT"),
            ("stopped_at", "TEXT"),
            ("health_check_url", "TEXT"),
            ("deployed_sha", "TEXT"),
            ("created_at", "TEXT"),
        ],
        "notes": (
            "Branch/item-scoped ephemeral preview environment rows. "
            "Agent-facing creation uses `yoke ephemeral-env create <project> "
            "<branch>` (`ephemeral_env.create`), and lifecycle field writes "
            "read through `yoke ephemeral-env get <project> <branch> --json` "
            "(`ephemeral_env.get`) and write through `yoke ephemeral-env update "
            "<env-id> <field> <value>` (`ephemeral_env.update`), not retained "
            "domain commands. Conduct "
            "uses branch `PREFIX-{id}`."
        ),
    },
}


__all__ = ["DELIVERY_TABLES"]
