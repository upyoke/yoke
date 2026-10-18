"""QA plan provenance and retirement for the canonical schema packet."""

QA_PLAN_TABLES = {
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
            "atomically by qa.plan_cases.sync. Frozen plan snapshots keep "
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
