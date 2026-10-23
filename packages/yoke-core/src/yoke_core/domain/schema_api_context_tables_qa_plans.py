"""QA plan provenance and retirement for the canonical schema packet."""

QA_PLAN_TABLES = {
    "qa_plan_executions": {
        "columns": [
            ("id", "TEXT"),
            ("roster_json", "TEXT"),
            ("roster_digest", "TEXT"),
            ("cursor_ordinal", "INTEGER"),
            ("state", "TEXT"),
            ("machine_lease_id", "INTEGER"),
            ("created_at", "TIMESTAMPTZ"),
            ("completed_at", "TIMESTAMPTZ"),
        ],
        "notes": (
            "The durable case roster is JSON text in roster_json, not a roster "
            "column. Domain execution dictionaries expose it as roster; SQL "
            "must use roster_json."
        ),
    },
    "qa_plan_execution_adoptions": {
        "columns": [
            ("id", "TEXT"),
            ("execution_id", "TEXT"),
            ("item_id", "INTEGER"),
            ("work_claim_id", "INTEGER"),
            ("previous_actor_id", "TEXT"),
            ("previous_session_id", "TEXT"),
            ("actor_id", "TEXT"),
            ("session_id", "TEXT"),
            ("reason", "TEXT"),
            ("adopted_at", "TIMESTAMPTZ"),
        ],
        "notes": (
            "Durable qa.plan_execution.adopt receipts, committed atomically "
            "with execution ownership. An ended predecessor and the execution "
            "item's current work holder are required; telemetry is not authority."
        ),
    },
    "qa_plan_execution_reconciliations": {
        "columns": [
            ("id", "TEXT"),
            ("execution_id", "TEXT"),
            ("actor_id", "TEXT"),
            ("session_id", "TEXT"),
            ("reason", "TEXT"),
            ("outcome", "TEXT"),
            ("prior_state", "TEXT"),
            ("prior_actor_id", "TEXT"),
            ("prior_session_id", "TEXT"),
            ("released_lease_ids", "TEXT"),
            ("reconciled_at", "TIMESTAMPTZ"),
        ],
        "notes": (
            "Durable qa.plan_execution.reconcile receipts, committed atomically "
            "with the settlement. A covering steering seat settles an execution "
            "whose owner stopped reporting: released_lease_ids is a JSON list, "
            "outcome is review_handoff (the caller owns the pending review) or "
            "aborted (no verdict)."
        ),
    },
    "qa_plans": {
        "columns": [
            ("id", "INTEGER"),
            ("project_id", "INTEGER"),
            ("slug", "TEXT"),
            ("name", "TEXT"),
            ("description", "TEXT"),
            ("success_policy_id", "TEXT"),
            ("success_policy_params", "TEXT"),
            ("target_environment_id", "INTEGER"),
            ("source_revision", "TEXT"),
            ("created_at", "TIMESTAMPTZ"),
            ("updated_at", "TIMESTAMPTZ"),
            ("retired_at", "TIMESTAMPTZ"),
            ("retirement_reason", "TEXT"),
            ("retired_by_actor_id", "INTEGER"),
        ],
        "notes": (
            "Plans belong to project_id (integer projects.id), not a project "
            "column or slug; use qa.plan.list for project-scoped catalog reads. "
            "source_revision is the full merged case-export commit, recorded "
            "atomically by qa.plan_cases.sync, or by server boot when the "
            "serving build generates the plan's cases and they drifted; boot "
            "only moves it forward. Frozen plan snapshots keep "
            "this provenance; deployment materialization/refresh refuses "
            "qa_plan_source_candidate_mismatch when the candidate does not "
            "carry it. Source-bound plans cannot drop provenance or use the "
            "interactive editor; manually authored correction plans are separate. "
            "qa.plan.retire records retired_at with retirement_reason and "
            "retired_by_actor_id once no unsettled requirement, live "
            "execution or project default depends on the plan; retired "
            "plans stay readable but refuse edits and materialization."
        ),
    },
}
