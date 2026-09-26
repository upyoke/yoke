"""``project`` topic delivery-lane table entries for the schema cheat sheet.

Sibling of :mod:`schema_api_context_tables` (which combines per-topic
dicts into the canonical ``CANONICAL_TABLES``). Holds deployment flows,
runs, stage receipts, run items, and ephemeral environments.

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
            ("definition_schema_version", "INTEGER"),
            ("takes_delivery_custody", "INTEGER"),
            ("supersedes_flow_id", "TEXT"),
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
            "`supersedes_flow_id` links immutable definition identities once "
            "a run references a flow. "
            "`definition_schema_version` names the stage vocabulary the "
            "executor reads: advanced release-policy definitions may be "
            "stored disabled, but cannot be activated, assigned, or started "
            "until the engine supports them. `takes_delivery_custody` is the "
            "authored delivery-custody declaration (INTEGER 0/1), independent "
            "of that version — adding `stage_kind` does not enroll items. "
            "`stages` is an ordered JSON array. Schema v2 gives every "
            "stage an execution/QA kind, a run/item scope, an explicit "
            "persistent or prior-preview target, reusable QA plan/case "
            "selection, verdict authority, and informational notification "
            "recipients. A `human-approval` stage names who "
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
            ("bound_sources", "TEXT"),
            ("candidate_containment", "TEXT"),
            ("artifact_identity", "TEXT"),
            ("composition_resolution", "TEXT"),
            ("composition_frozen_at", "TEXT"),
            ("requirement_snapshot", "TEXT"),
            ("driver_attachment", "TEXT"),
            ("settling_at", "TEXT"),
        ],
        "notes": (
            "One row per deployment-flow execution. Primary key is the "
            "TEXT `id` (run identifier like 'run-YYYYMMDD-NNN'); the "
            "`flow` column joins to `deployment_flows.id`. There is no "
            "`item_id` column on this table. Item-bound delivery joins "
            "through `deployment_run_items`. Use `deployment_runs.id` in "
            "raw run queries; do not look for a `run_id` column on the run "
            "table (that column lives on `deployment_run_items`). Membership "
            "is empty while status is 'created' and is filled at the start "
            "from the candidate; a run that stays empty is an environment "
            "release and still advances this run row. Schema-v1 flows never "
            "enroll, so they stay empty through execution too: "
            "`deployment_runs.list` still projects the items whose recorded "
            "merge the pinned candidate contains as `contained_items`, read "
            "in O(1) from the start-time `candidate_containment` snapshot, which "
            "is the Frontier card's live-run join key, not membership, and "
            "does not take delivery custody. To "
            "start a schema-v2 run, `release_lineage` must be a full commit "
            "SHA and every delivery-ready carried item must be admitted. The "
            "run then freezes member/flow requirement snapshots and any "
            "distinct shared artifact identity. Missing "
            "first-baseline attribution requires an explicit "
            "`composition_resolution`. Schema-v1 runs keep legacy start "
            "behavior. To "
            "read what any succeeded run actually shipped, inspect the "
            "`carried_work` JSON object: `items` are attribution matches, "
            "`commits` are unresolved bare SHAs, and `derivation.reason` "
            "names an explicit empty result. When `warnings` change what "
            "the run can attest, `deployment_runs.get` projects "
            "`attestation_warnings` (reason, cost, recovery) and the "
            "deploy pipeline prints the same; do not parse `carried_work` "
            "JSON for that downgrade. It is independent of member "
            "lifecycle. A run that binds another project's source through a "
            "stage `input_bindings` records the commit it resolved for that "
            "project in the `bound_sources` JSON object, so membership, "
            "delivery and run detail all read one recorded commit per "
            "project instead of re-resolving a branch. That same per-project "
            "entry carries an `outputs` list naming commits the run's own "
            "release automation pushed into that project (a version-pin "
            "materialization, typically), written by "
            "`deployment_runs.release_output.record`; carried-work "
            "attribution reads it only for a commit no item claimed and "
            "reports those under `release_output`, so a release that wrote a "
            "commit no longer reads as unattributed carried work. To "
            "approve an executing run whose current flow stage uses the "
            "`human-approval` executor, use `yoke deployment-runs approve "
            "RUN-ID [--note TEXT]`; the run stage is authoritative and Yoke "
            "synchronizes member item stage caches atomically. To "
            "find the active deploy run for an item, JOIN through "
            "`deployment_run_items`: `SELECT dr.id, dr.status, "
            "dr.current_stage, dr.target_environment_id FROM deployment_runs dr "
            "JOIN deployment_run_items dri ON dri.run_id = dr.id WHERE "
            "dri.item_id = ? ORDER BY dr.created_at DESC LIMIT 1;`. "
            "`driver_attachment` is JSON naming the live process driving "
            "the run (`session_id`, `pid`, `attached_at`, `heartbeat_at`, "
            "`phase`, `progress_capture`). A second execute of a run whose "
            "attachment is still live refuses by name; an empty or stale "
            "attachment is an interrupted driver, recovered by re-driving "
            "the same run id. "
            "`settling_at` marks an `executing` run whose shared gates "
            "passed and which is closing its cleared members before it may "
            "read `succeeded`; completion authority treats it as delivered, "
            "and re-driving `status succeeded` replays the settlement. "
            "Stale-run HCs scan rows where `status` is non-terminal "
            "but `started_at` is older than the configured cutoff; "
            "item-less is suspicious only when a run never starts."
            " New run creation locks `deployment_runs` in Postgres, computes "
            "the UTC day's maximum numeric suffix plus one, and inserts under "
            "the same transaction with the primary key as a collision guard. "
            "`runs next-id` is only a non-reserving preview. The selected "
            "final member close-out reader is "
            "`deployment_member_independent_close_out`; it imports "
            "`deployment_run_composition_freeze.DELIVERY_INTENT_FINAL` at call "
            "time because a module-level import creates a circular import. "
            "The prior-QA-stage refusal reader is "
            "`deployment_qa_stage_resume.prior_deployment_qa_refusals`, not "
            "`deployment_qa_stage_prerequisites` (stale module guess)."
        ),
    },
    "deployment_stage_receipts": {
        "columns": [
            ("id", "INTEGER"),
            ("run_id", "TEXT"),
            ("stage_name", "TEXT"),
            ("attempt_number", "INTEGER"),
            ("correlation_id", "TEXT"),
            ("target_kind", "TEXT"),
            ("target_name", "TEXT"),
            ("status", "TEXT"),
            ("observed_url", "TEXT"),
            ("observed_release_lineage", "TEXT"),
            ("observed_artifact_identity", "TEXT"),
            ("executor", "TEXT"),
            ("executor_receipt", "TEXT"),
            ("failure_reason", "TEXT"),
            ("created_at", "TEXT"),
            ("completed_at", "TEXT"),
        ],
        "notes": (
            "Durable ordered observations from non-QA deployment attempts. "
            "Allocate attempt identity before dispatch. Identical correlation "
            "replay is idempotent; terminal callbacks are immutable and "
            "failures preserve recovery reasons. Scoped QA accepts only the "
            "newest ready receipt for its pinned `source_stage`, exact target "
            "and release lineage, and any pinned artifact identity. Older or "
            "superseded success never satisfies QA; events are telemetry."
        ),
    },
    "deployment_run_items": {
        "columns": [
            ("run_id", "TEXT"),
            ("item_id", "INTEGER"),
            ("added_at", "TEXT"),
            ("delivery_intent", "TEXT"),
            ("requirement_selection", "TEXT"),
            ("requirement_snapshot", "TEXT"),
            ("containment_attestation", "TEXT"),
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
            "`created`. For schema-v2 releases, `delivery_intent` is "
            "`progress` or `final`; the explicit requirement selection and "
            "the full selected requirement/plan/case content are frozen when "
            "the run starts. `containment_attestation` is the JSON evidence "
            "for a containment verdict a lane checkout answered when this "
            "control plane's own repository sources could not: both compared "
            "commits, which test decided, and when it was recorded."
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
