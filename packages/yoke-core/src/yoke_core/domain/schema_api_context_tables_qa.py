"""``qa`` topic table entries for the schema cheat sheet.

Pure data only — no I/O or DB connections; composes sibling plan facts.
"""

from __future__ import annotations
from yoke_core.domain.schema_api_context_tables_qa_plans import QA_PLAN_TABLES
from yoke_core.domain.schema_api_context_tables_qa_evidence import QA_EVIDENCE_TABLES


QA_TABLES: dict[str, dict] = {
    **QA_PLAN_TABLES,
    "shepherd_verdicts": {
        "columns": [
            ("id", "INTEGER"),
            ("public_ref", "TEXT"),
            ("archived_item_key", "TEXT"),
            ("transition", "TEXT"),
            ("worker", "TEXT"),
            ("verdict", "TEXT"),
            ("caveats", "TEXT"),
            ("attempt", "INTEGER"),
            ("created_at", "TIMESTAMPTZ"),
        ],
        "notes": (
            "The reviewer name is worker; reviewer is not a column. "
            "The active item key is public_ref, rendered from the item's "
            "project prefix and project_sequence. Numeric items.id remains "
            "an internal join key. The prior item column encoded legacy "
            "internal-id tokens; only the governed migration transforms it. "
            "Unresolvable historical rows have NULL public_ref and preserve "
            "their original key in archived_item_key; active readers never alias it."
        ),
    },
    "qa_requirements": {
        "columns": [
            ("id", "INTEGER"),
            ("item_id", "INTEGER"),
            ("epic_id", "INTEGER"),
            ("task_num", "INTEGER"),
            ("deployment_run_id", "TEXT"),
            ("deployment_stage", "TEXT"),
            ("deployment_member_item_id", "INTEGER"),
            ("qa_kind", "TEXT"),
            ("qa_phase", "TEXT"),
            ("target_env", "TEXT"),
            ("blocking_mode", "TEXT"),
            ("requirement_source", "TEXT"),
            ("success_policy", "TEXT"),
            ("capability_requirements", "TEXT"),
            ("suite_id", "TEXT"),
            ("waived_at", "TIMESTAMPTZ"),
            ("waiver_rationale", "TEXT"),
            ("waiver_source", "TEXT"),
            ("retracted_at", "TIMESTAMPTZ"),
            ("retraction_rationale", "TEXT"),
            ("retraction_source", "TEXT"),
            ("replacement_requirement_id", "INTEGER"),
            ("plan_id", "INTEGER"),
            ("plan_case_key", "TEXT"),
            ("case_position", "INTEGER"),
            ("baseline_position", "INTEGER"),
            ("method_id", "TEXT"),
            ("method_name", "TEXT"),
            ("runner_id", "TEXT"),
            ("verdict_path", "TEXT"),
            ("host_baseline", "TEXT"),
            ("starting_state", "TEXT"),
            ("starting_state_reason", "TEXT"),
            ("entry_surface", "TEXT"),
            ("required_completion", "TEXT"),
            ("workflow_transition_id", "TEXT"),
            ("instructions", "TEXT"),
            ("expected_outcome", "TEXT"),
            ("method_config", "TEXT"),
            ("execution_target_json", "TEXT"),
            ("execution_target_digest", "TEXT"),
            ("rebound_at", "TIMESTAMPTZ"),
            ("rebound_from_digest", "TEXT"),
            ("rebind_rationale", "TEXT"),
            ("rebind_actor_id", "INTEGER"),
            ("rebound_from_target_json", "TEXT"),
            ("rebind_endpoint_delta_json", "TEXT"),
            ("wake_path", "TEXT"),
            ("wake_evidence", "TEXT"),
            ("covered_item_ids", "TEXT"),
            ("created_at", "TIMESTAMPTZ"),
        ],
        "notes": (
            "Manual-notice settlement reads waived_at, superseded_at and retracted_at. "
            "Wrong guess: api_items_fixture_schema may omit superseded_at or retracted_at; "
            "its lifecycle cancellation path settles the same QA notices. "
            "qa_test_helpers and qa_full_test_helpers supply deployment_runs status and "
            "qa_requirements.superseded_by_requirement_id for admitted-copy reconciliation; "
            "qa.cmd_init alone lacks the latter (the undefined-column cause). "
            "Wrong fixture assumption: create_core_tables supplies a complete QA schema; "
            "its initial qa_requirements lacks retracted_at and superseded_by_requirement_id. "
            "Tests needing only history use item_status_transitions.ensure_schema instead. "
            "failed_qa_owner_sql needs qa_requirements.execution_target_json; "
            "deployment_run_id alone cannot describe inherited ownership. "
            "Adding item_sections also needs qa_requirements.qa_kind/item_id and "
            "qa_runs.case_outcome/raw_result for qa_simulation_triage.triage_discharge_sql. "
            "Deployment QA test fixtures use "
            "runtime.api.fixtures.completed_delivery.seed_selected_requirement_run; "
            "the stage environment fixture is runtime.api.domain.deployment_qa_stage_execution_test_support._environment, "
            "not test_deployment_qa_admission_execution._environment. "
            "Plan detail reads use qa_plan_detail.get_plan(conn, plan_id=...), not plan_detail. "
            "covered_item_ids lists members a closed shared plan group answered. "
            "member_group_blockers belongs to deployment_qa_plan_group_standings; "
            "importing it from deployment_qa_plan_group_writes is the obsolete guess. "
            "QA cases declare target_envs as a JSON list; each environment "
            "materializes a separate target_env obligation and done requires every target. "
            "qa_plan_cases.stage_reason (creates_or_destroys_data or "
            "changes_infrastructure) is optional descriptive metadata; "
            "it does not restrict target_envs. "
            "wake_path (automatic default, or manual with a one-line "
            "wake_evidence) rides plan cases into requirements. "
            "Requirements describe what passing looks like; verdicts and "
            "raw results live on qa_runs (joined via qa_requirement_id). "
            "Reviewed-implementation gate verifies a passing run exists "
            "per requirement; running the test suite alone does not "
            "satisfy the gate. Blocking state is `blocking_mode`; there "
            "is NO `is_blocking` column. Primary key is `id`, not "
            "`requirement_id`; requirement rows do not carry `status` "
            "or `last_known_result`. "
            "`replacement_requirement_id` declares a corrected case; "
            "`superseded_by_requirement_id` records discharge. Missing preview "
            "columns need serving boot convergence through "
            "`yoke_core.api.server_entrypoint.ensure_core_schema`. Schema owner: "
            "`yoke_core.domain.qa_catalog_schema`; `qa_requirements_schema` "
            "and `server_boot` are guessed, nonexistent modules. "
            "Manual plan snapshots use `qa_standalone_execution."
            "begin_standalone_execution`; its guessed `host_capability_kinds` "
            "argument does not exist. Host capabilities are resolved internally "
            "from the acting session. Machine-run cases (host_control and "
            "agent_mission runners) carry `starting_state` (`baseline`, "
            "`inherit`, `as_is`) and `starting_state_reason`; "
            "`yoke_core.domain.qa_plan_case_chain` owns chain ends and the "
            "inherit blocker. Plan and requirement reads select the stored "
            "starting-state and target fields explicitly. "
            "`qa_case_starting_state_schema` "
            "and `schema_sql` are guessed modules, not schema owners. "
            "Plan bindings live in qa_plan_item_attachments; its timestamp is "
            "attached_at, not created_at. Attachment fixture inserts use attached_at and transition_id; wrong guesses created_at and workflow_transition are not its columns. "
            "A retracted row (`retracted_at`) is withdrawn history from "
            "`yoke qa item-plan retract`, not a waiver and not a "
            "supersession. "
            "Release admission and frozen member selection skip withdrawn "
            "requirements and attachments. Repeat `yoke qa item-plan retract` "
            "to retire copies older builds created after withdrawal, then "
            "re-drive the run or execute its member-scoped QA stage. "
            "Source-test status reads use `deployment_qa_stage_gate."
            "deployment_qa_stage_status(conn, run_id=..., stage_name=..., "
            "member_item_id=...)`; the materializer's `deployment_run_id`, "
            "`deployment_stage`, `deployment_member_item_id` keywords do "
            "not belong to that status helper. "
            "Deployment requirements may additionally bind the frozen stage "
            "and optional attached member through `deployment_stage` and "
            "`deployment_member_item_id`; both stay NULL on legacy run subjects. "
            "`capability_requirements` is a canonical JSON array of capability "
            "kinds; `[]` means the case has no capability prerequisite. Case "
            "admission resolves those kinds against the project's "
            "`project_capabilities` rows plus the harness session's manifest, "
            "except for kinds this case's OWN `runner_id` is declared to supply "
            "where it executes (`qa_method_capabilities."
            "RUNNER_HOST_PROVISIONED_CAPABILITY_KINDS`: `browser_substrate`, "
            "whose daemon start installs the browser runtime on this machine, "
            "and `agent_mission`, whose dispatch contract requires the walker to "
            "run `yoke qa browser setup` on its target host). No project row "
            "proves or withholds those, so admission admits them and each "
            "runner's own path supplies them on first use; adding an empty "
            "`browser-control` project row is a stale workaround, not the "
            "contract. The exemption is per runner, never per kind: a "
            "`worktree_run` or `ci_run` case declaring `browser-control` is "
            "still refused, and `test-machine` stays a gate for every runner. "
            "The aggregate discriminator is `qa_kind` "
            "(values like `ac_verification` / `implementation_review`) — "
            "there is no `kind` and no `requirement_type` column; "
            "requirement provenance is `requirement_source` (`explicit` / "
            "The runner a case selects is `runner_id` (values `worktree_run` / "
            "`ci_run` / `browser_substrate` / `host_control` / "
            "`agent_mission`); it is NOT named "
            "`executor_id`, and plain `executor` on this table is a stale guess — "
            "that word now names harness identity only, on "
            "`harness_sessions.executor`. "
            "`ac_derived` / ...). Materialized executable cases instead "
            "carry immutable case ordering, runner, entry-surface, "
            "completion, instructions, expected-outcome, and method-config "
            "snapshots plus one environment/tenant/project execution target. "
            "The target digest prevents endpoint or environment substitution "
            "after materialization. Rebind a same-environment declaration via "
            "`yoke qa requirement rebind-target` only when resolved host "
            "authority is unchanged; a repointed host refuses. Identity is "
            "not host. Previous JSON and the endpoint delta stay on the row. "
            "Execute a transition's ordered set through "
            "`yoke qa plan run --item PREFIX-N --transition T`, or one "
            "snapshot through `yoke qa case run --requirement-id <id>`; "
            "never replace snapshot fields during execution. "
            "A green run satisfies only while it still proves live method_config "
            "and the live execution-target digest (`has_current_passing_run`); "
            "a sanctioned rebind keeps a prior pass current. "
            "EXISTS(verdict=pass) is not current. "
            "Runners stamp executed method_config and the start-bound target "
            "digest into raw_result at start; complete keeps those snapshots. "
            "An in-place method_config correction records a revision marker on "
            "the requirement; once set it stays, including through empty "
            "config, and unstamped greens then no longer satisfy. "
            "A target_env correction persists the live snapshot rather than "
            "that marker, and a green recorded against a different digest "
            "no longer satisfies. "
            "Correct a live capture script with `yoke qa requirement update "
            "--field method_config`; frozen deployment-run rows refuse that write. "
            "Canonical unsatisfied-verification SELECT: "
            "`SELECT qr.id, qr.qa_kind, qr.method_id, qr.expected_outcome, "
            "qr.method_config, qr.blocking_mode "
            "FROM qa_requirements qr WHERE qr.item_id = %s "
            "AND qr.qa_phase = 'verification' AND qr.waived_at IS NULL`."
        ),
    },
    **QA_EVIDENCE_TABLES,
}
