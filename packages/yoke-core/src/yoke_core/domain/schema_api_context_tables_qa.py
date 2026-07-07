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
            "The kind discriminator is `qa_kind` (values like "
            "`ac_verification` / `browser_smoke` / "
            "`implementation_review`) — there is no `kind` and no "
            "`requirement_type` column; requirement provenance is "
            "`requirement_source` (`explicit` / `ac_derived` / ...). "
            "Canonical unsatisfied-verification SELECT: "
            "`SELECT qr.id, qr.qa_kind, qr.blocking_mode, qr.success_policy "
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
            ("executor_type", "TEXT"),
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
            "qa_requirement_id. Browser-kind requirements (browser_smoke, "
            "browser_diff) require executor_type=browser_substrate; "
            "agent runs are rejected for those kinds. Tester review "
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
            "Browser-QA execution shape: `yoke qa browser run --item "
            "PREFIX-N [--project P] [--base-url URL]` (tool-shaped "
            "launcher token; works from any project checkout because its "
            "DB legs are the dispatcher ids qa.browser_context.get / "
            "qa.run.add / qa.run.complete / qa.artifact.add — there is "
            "NO browser_qa.run function id). The internal browser-QA "
            "module form only works "
            "inside a Yoke checkout, and the orchestrator takes NO "
            "`--db` flag (the retired db-path token was purged with the "
            "resolve_db_path guard)."
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
