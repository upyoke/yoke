"""QA run and artifact facts for the schema context catalog."""

from __future__ import annotations

QA_EVIDENCE_TABLES: dict[str, dict] = {
    "qa_runs": {
        "columns": [
            ("id", "INTEGER"),
            ("qa_requirement_id", "INTEGER"),
            ("performed_by", "TEXT"),
            ("qa_kind", "TEXT"),
            ("verdict", "TEXT"),
            ("verdict_reason", "TEXT"),
            ("score", "REAL"),
            ("confidence", "REAL"),
            ("raw_result", "TEXT"),
            ("duration_ms", "INTEGER"),
            ("started_at", "TIMESTAMPTZ"),
            ("completed_at", "TIMESTAMPTZ"),
            ("created_at", "TIMESTAMPTZ"),
            ("execution_status", "TEXT"),
            ("case_outcome", "TEXT"),
            ("capture_degraded_reason", "TEXT"),
        ],
        "notes": (
            "Recorded results. Join to qa_requirements via "
            "Who or what produced the run is `performed_by` (free text: `agent`, "
            "`human`, `pytest`, `github-actions`, `ci_run`, `browser_substrate`, "
            "`host_control`, `agent_mission`, "
            "...); it is NOT named `executor_type` and is NOT a closed runner "
            "enum. The `--performed-by` flag on `yoke qa run add` and "
            "`yoke qa run record-verdict` writes it. "
            "qa_requirement_id. Requirements whose method_id is "
            "`browser-check` or `browser-inspection` require "
            "performed_by=browser_substrate; agent runs are rejected for "
            "those methods. Tester review "
            "verdicts (`yoke workflow-item epic-task review-insert`) "
            "ALSO land here — verdict + "
            "raw_result.body live on a qa_runs row with "
            "qa_kind='implementation_review' joined to a "
            "qa_requirements row of the same kind. There is no separate "
            "epic_reviews / epic_task_reviews table. qa_task_review_candidate "
            "owns task checkout reads, not qa_run_commit_binding._git "
            "(removed); commit observations belong to the run writer. There is NO "
            "`requirement_id` column and NO `result` column; use "
            "`qa_requirement_id`, `verdict`, and `raw_result`. "
            "There is no `error_message` column: `verdict_reason` holds the "
            "summary; mission preparation diagnostics and baseline receipts "
            "live in `raw_result.preparation.evidence`. Preparation failure "
            "uses `verdict=error`, `case_outcome=blocked_on_precondition` "
            "and `execution_status=capture_failed`; `error` is not a stored "
            "case_outcome. "
            "JSON: `json_helper.dumps_compact` / `dumps_pretty`, no `dumps` export. "
            "Proof views use `qa_plan_case_proof._case_result`; "
            "there is no `latest_case_proof` export. "
            "`execution_status` is capture-stage bookkeeping for browser and "
            "agent-mission runs (captured | capture_failed), distinct from the quality "
            "`verdict`. `captured` requires at least one `qa_artifacts` row, or a "
            "named `capture_degraded_reason` when the capture produced none; "
            "the write refuses `captured` with a NULL reason and zero artifacts. "
            "`ci_run` / `github-actions` runs do not claim `captured`; their "
            "proof is `raw_result.verification_tree.head_sha` plus `run_url`, "
            "and missing artifacts is not missing proof. Do not invent a "
            "substitute artifact for that display, and do not treat an "
            "`agent` run's `capture_run_id` as an evidence gap. "
            "`capture_failed` names what failed to capture and why. A failing "
            "browser assertion records page evidence without an authored "
            "screenshot step. "
            "Agent `undetermined` requires `verdict_reason` plus a "
            "linked artifact and halts the item for owner/operator review; an "
            "unstarted case uses `blocked_on_precondition`, not review. "
            "Browser method execution shape: `yoke qa case run "
            "--requirement-id R --base-url URL --expected-branch BRANCH "
            "--expected-sha SHA`. The runner reads the immutable case "
            "through the write-authorized qa.case_execution.begin before "
            "local work and owns the qa.run.add / qa.run.complete / "
            "qa.artifact.add evidence writes for that single requirement. "
            "Those writes stamp executed method_config into raw_result at "
            "run start; complete retains that snapshot so an in-flight "
            "completion cannot prove a later live config."
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
            ("created_at", "TIMESTAMPTZ"),
        ],
        "notes": (
            "Join qa_runs via qa_run_id for qa_requirement_id; qa_artifacts "
            "has no qa_requirement_id or filename column. Filename is input, "
            "stored in metadata. File reference: artifact_handle, typed JSON "
            '({"backend":"s3","bucket":B,"key":K} for uploaded evidence, '
            '{"backend":"local","path":P} for explicit machine-local '
            "evidence). No storage_path column; bare paths refuse. "
            "Inline client bytes: pass "
            "`content_base64` plus `filename` (and optional `content_type`) "
            "instead of `artifact_handle` — the two inputs are mutually "
            "exclusive. Every byte submission stores under the requirement's "
            "item or deployment-run owner in the configured project S3 store. "
            "Only a genuinely absent bucket selects permanent server-local "
            "application-data storage. A configured store with invalid "
            "credentials or a failed upload returns its real error and creates "
            "no evidence row. Submission and inline-read size are bounded at "
            "20MiB. CLI: "
            "`yoke qa artifact add --requirement-id N --run-id N "
            "--artifact-type screenshot --content-base64 B64 --filename F` "
            "or `--content-file PATH`. Durable upload flow: "
            "qa.artifact.presign mints a presigned S3 PUT (CLI adapter "
            "`yoke qa artifact presign --requirement-id N --run-id N "
            "--filename F`), the client uploads over plain HTTPS, then "
            "records the returned handle via qa.artifact.add. "
            "s3_not_configured from presign means no environment of the "
            "project declares environments.settings.artifacts.bucket — "
            "submit bytes and let the server use its permanent local fallback. "
            "Hosted tenants use the YOKE_QA_ARTIFACT_* broker URL, token-file, "
            "bucket, and immutable prefix settings; they receive no AWS "
            "credentials, and foreign-prefix S3 handles are refused. "
            "Direct local handles must already be readable server evidence; "
            "qa.artifact.add ingests their bytes through the same storage "
            "policy before recording the row. Reading evidence back: "
            "`yoke qa artifact read --requirement-id N --artifact-id N` "
            "lands the bytes at a path your own path guard admits and "
            "reports it as `path`; `--output PATH` picks a different "
            "destination. Do NOT open a capture's reported `artifacts` "
            "paths or `artifact_handle.path` — both address the capturing "
            "machine's ephemeral per-run scratch, which may live on another "
            "machine. Use the registered read to retrieve stored bytes. "
            "Capture completion reports "
            "`artifact_ids` plus a ready `artifact_reads` command per "
            "artifact, and review bundles carry `read_command` on each "
            "artifact, so the id never has to be hunted for. "
            "Artifact hand-back queries import json_get from yoke_core.domain.sql_json; "
            "db_backend has no json_get export."
        ),
    },
}
