"""``qa`` topic table entries for the schema cheat sheet.

Sibling of :mod:`schema_api_context_tables` (which combines per-topic
dicts into the canonical ``CANONICAL_TABLES``). Holds the ``qa`` topic
entries: qa_requirements, qa_runs, qa_artifacts.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations


QA_TABLES: dict[str, dict] = {
    "qa_requirements": {
        "columns": [
            ("id", "INTEGER"),
            ("item_id", "INTEGER"),
            ("epic_id", "INTEGER"),
            ("task_num", "INTEGER"),
            ("deployment_run_id", "TEXT"),
            ("qa_kind", "TEXT"),
            ("qa_phase", "TEXT"),
            ("target_env", "TEXT"),
            ("blocking_mode", "TEXT"),
            ("requirement_source", "TEXT"),
            ("success_policy", "TEXT"),
            ("capability_requirements", "TEXT"),
            ("suite_id", "TEXT"),
            ("waived_at", "TEXT"),
            ("waiver_rationale", "TEXT"),
            ("waiver_source", "TEXT"),
            ("plan_id", "INTEGER"),
            ("plan_case_key", "TEXT"),
            ("case_position", "INTEGER"),
            ("baseline_position", "INTEGER"),
            ("method_id", "TEXT"),
            ("method_name", "TEXT"),
            ("runner_id", "TEXT"),
            ("required_capability_kind", "TEXT"),
            ("verdict_path", "TEXT"),
            ("host_baseline", "TEXT"),
            ("entry_surface", "TEXT"),
            ("required_completion", "TEXT"),
            ("workflow_transition_id", "TEXT"),
            ("instructions", "TEXT"),
            ("expected_outcome", "TEXT"),
            ("method_config", "TEXT"),
            ("execution_target_json", "TEXT"),
            ("execution_target_digest", "TEXT"),
            ("created_at", "TEXT"),
        ],
        "notes": (
            "Requirements describe what passing looks like; verdicts and "
            "raw results live on qa_runs (joined via qa_requirement_id). "
            "Reviewed-implementation gate verifies a passing run exists "
            "per requirement; running the test suite alone does not "
            "satisfy the gate. Blocking state is `blocking_mode`; there "
            "is NO `is_blocking` column. Primary key is `id`, not "
            "`requirement_id`; requirement rows do not carry `status` "
            "or `last_known_result`. "
            "The aggregate discriminator is `qa_kind` "
            "(values like `ac_verification` / `implementation_review`) — "
            "there is no `kind` and no `requirement_type` column; "
            "requirement provenance is `requirement_source` (`explicit` / "
            "`ac_derived` / ...). Materialized executable cases instead "
            "carry immutable case ordering, runner, entry-surface, "
            "completion, instructions, expected-outcome, and method-config "
            "snapshots plus one environment/tenant/project execution target. "
            "The target digest prevents endpoint or environment substitution "
            "after materialization. Execute a transition's ordered set through "
            "`yoke qa plan run --item PREFIX-N --transition T`, or one "
            "snapshot through `yoke qa case run --requirement-id <id>`; "
            "never replace snapshot fields during execution. "
            "Canonical unsatisfied-verification SELECT: "
            "`SELECT qr.id, qr.qa_kind, qr.method_id, qr.expected_outcome, "
            "qr.method_config, qr.blocking_mode "
            "FROM qa_requirements qr WHERE qr.item_id = %s "
            "AND qr.qa_phase = 'verification' AND qr.waived_at IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM qa_runs qrun "
            "WHERE qrun.qa_requirement_id = qr.id AND qrun.verdict = 'pass')`."
        ),
    },
    "qa_runs": {
        "columns": [
            ("id", "INTEGER"),
            ("qa_requirement_id", "INTEGER"),
            ("performed_by", "TEXT"),
            ("qa_kind", "TEXT"),
            ("verdict", "TEXT"),
            ("score", "REAL"),
            ("confidence", "REAL"),
            ("raw_result", "TEXT"),
            ("duration_ms", "INTEGER"),
            ("started_at", "TEXT"),
            ("completed_at", "TEXT"),
            ("created_at", "TEXT"),
            ("execution_status", "TEXT"),
        ],
        "notes": (
            "Recorded results. Join to qa_requirements via "
            "qa_requirement_id. Requirements whose method_id is "
            "`browser-check` or `browser-inspection` require "
            "performed_by=browser_substrate; agent runs are rejected for "
            "those methods. Tester review "
            "verdicts (`yoke workflow-item epic-task review-insert`) "
            "ALSO land here — verdict + "
            "raw_result.body live on a qa_runs row with "
            "qa_kind='implementation_review' joined to a "
            "qa_requirements row of the same kind. There is no separate "
            "epic_reviews / epic_task_reviews table. There is NO "
            "`requirement_id` column and NO `result` column; use "
            "`qa_requirement_id`, `verdict`, and `raw_result`. "
            "`execution_status` is the browser capture outcome "
            "(captured | capture_failed), distinct from the quality "
            "`verdict`. "
            "Browser method execution shape: `yoke qa case run "
            "--requirement-id R --base-url URL --expected-branch BRANCH "
            "--expected-sha SHA`. The runner reads the immutable case "
            "through the write-authorized qa.case_execution.begin before "
            "local work and owns the qa.run.add / qa.run.complete / "
            "qa.artifact.add evidence writes for that single requirement."
        ),
    },
    "qa_artifacts": {
        "columns": [
            ("id", "INTEGER"),
            ("qa_run_id", "INTEGER"),
            ("artifact_type", "TEXT"),
            ("content_type", "TEXT"),
            ("artifact_handle", "TEXT"),
            ("metadata", "TEXT"),
            ("created_at", "TEXT"),
        ],
        "notes": (
            "Evidence rows joined to qa_runs via qa_run_id. The file "
            "reference is `artifact_handle` — typed JSON "
            '({"backend":"s3","bucket":B,"key":K} for uploaded evidence, '
            '{"backend":"local","path":P} for explicit machine-local '
            "evidence). There is NO `storage_path` column (hard-cut; "
            "historical path rows were purged) and bare-path payloads "
            "are refused by qa.artifact.add. Durable upload flow: "
            "qa.artifact.presign mints a presigned S3 PUT (CLI adapter "
            "`yoke qa artifact presign --requirement-id N --run-id N "
            "--filename F`), the client uploads over plain HTTPS, then "
            "records the returned handle via qa.artifact.add. "
            "s3_not_configured from presign means no environment of the "
            "project declares environments.settings.artifacts.bucket — "
            "record an explicit local handle instead."
        ),
    },
}
