"""``qa`` topic wrapper-command recipes for the agent-context packet.

Sibling of :mod:`schema_api_context_commands` (which combines per-topic
lists into the canonical ``WRAPPER_COMMANDS``). Holds the ``qa`` topic
entries: QA requirement/run reads, run-verdict recording, gate preview,
gate summary, method-case materialization/execution, and the events read
recipe.

Recipe shape doctrine:
    The qa family teaches registered ``yoke`` forms — requirement
    list/get/add/add-batch, run add/list, gate-summary — with the
    db_router/domain multi-module forms surviving only as labelled
    operator-debug fallbacks (and as the sole surface for shapes the
    typed adapters deliberately omit: file-backed
    ``--raw-result-file``/``--artifact-path`` evidence, score /
    confidence fields, epic-task / deployment-run-attached
    requirement creation, ``qa_gates`` previews). Epic task list/body
    reads are wrapped (``yoke epic-tasks list`` / ``yoke
    workflow-item epic-task body-get``); the ``dispatch-chain-*`` CLIs
    have no ``yoke`` CLI adapter yet and stay multi-module.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations


QA_COMMANDS: list[dict] = [
    {
        "topic": "qa",
        "purpose": "List QA requirements for an item or epic",
        "recipe": "yoke qa requirement list --item PREFIX-N",
        "notes": (
            "Registered read qa.requirement.list (works over https). "
            "Use --epic-id E for epic-task requirements; filter by "
            "task_num client-side. One row by id: `yoke qa "
            "requirement get --requirement-id <id>`. "
            "qa_requirements.id is the PK. Do not teach requirement_id "
            "as a short-form column."
        ),
    },
    {
        "topic": "qa",
        "purpose": "List QA runs for a requirement",
        "recipe": "yoke qa run list --requirement-id <id>",
        "notes": (
            "Registered read qa.run.list (works over https). Verify "
            "recorded runs before claiming a verdict. Rows carry "
            "verdict (pass/fail), execution_status (capture outcome), "
            "raw_result (result payload). qa_runs.qa_requirement_id is "
            "the FK. Do not teach result as a short-form column."
        ),
    },
    {
        "topic": "qa",
        "purpose": "Get one QA run by id",
        "recipe": "yoke qa run get --run-id <id>",
        "notes": (
            "Registered read qa.run.get (works over https). Returns one "
            "qa_runs row including verdict, execution_status, raw_result, "
            "duration_ms, started_at, and completed_at."
        ),
    },
    {
        "topic": "qa",
        "purpose": "Add a QA requirement — ac_verification variant",
        "recipe": (
            "yoke qa requirement add "
            "--item PREFIX-N --qa-kind ac_verification --qa-phase verification "
            "--blocking-mode blocking --requirement-source ac_derived "
            "--workflow-transition reviewed-implementation"
        ),
        "notes": (
            "Registered write qa.requirement.add — item-claim-gated, "
            "item-attached. `--workflow-transition` is required and must "
            "name a stage in the item's pinned workflow that carries or "
            "precedes a qa_verification gate. ac_verification omits "
            "`--success-policy` "
            "by default; stricter policy is "
            '`{"min_runs":N,"min_pass":N}`. Several rows in one '
            "transaction: pipe a JSON array to `yoke qa requirement "
            "add-batch --item PREFIX-N --stdin`; every row must include "
            "`workflow_transition_id`. Epic-task attachment is "
            "operator-debug only and requires the same binding: "
            "`python3 -m yoke_core.domain.qa requirement-add "
            "--epic-id E --task-num K --workflow-transition STAGE ...`. "
            "Deployment-run attachment is operator-debug only and may "
            "omit the transition because the run owns its delivery context."
        ),
    },
    {
        "topic": "qa",
        "purpose": "Materialize attached QA plan cases for a transition",
        "recipe": (
            "yoke qa plan materialize --item PREFIX-N "
            "--transition reviewed-implementation"
        ),
        "notes": (
            "Registered write qa.plan.materialize. Materialization is "
            "idempotent and snapshots each attached plan case into one "
            "qa_requirements row carrying method_id, instructions, "
            "expected_outcome, immutable method_config, and the plan's "
            "environment/tenant/project execution target. Read the "
            "result with `yoke qa requirement list --item PREFIX-N`; "
            "standard materialization never rewrites an existing case snapshot. "
            "For a corrected definition, run `yoke qa plan rematerialize "
            "--item PREFIX-N --transition reviewed-implementation`; it refreshes "
            "matching requirements without losing runs, adds new cases, and waives "
            "removed cases."
        ),
    },
    {
        "topic": "qa",
        "purpose": "Edit a project QA plan as one compare-and-swap document",
        "recipe": "yoke qa plan edit release-readiness",
        "notes": (
            "Registered write qa.plan.edit. From a mapped project checkout, "
            "the command resolves project context, opens a clean JSON plan "
            "document in $VISUAL / $EDITOR, and saves metadata plus the full "
            "ordered case set and `target_environment_id` in one transaction. "
            "The environment must belong to the plan project and match the "
            "hosted runtime. A stale updated_at refuses "
            "the write and preserves the edited file. v1 accepts only the "
            "all-pass policy; materialized item requirements stay unchanged "
            "until an explicit re-materialization."
        ),
    },
    {
        "topic": "qa",
        "purpose": "Add a QA run verdict — agent × ac_verification (inline raw_result)",
        "recipe": (
            "yoke qa run add "
            "--requirement-id R --executor-type agent "
            "--qa-kind ac_verification --verdict pass "
            "--raw-result 'Full backend pytest passed: N passed, K skipped.'"
        ),
        "notes": (
            "Registered write qa.run.add — item claims remain required for "
            "item-backed requirements; deployment-run requirements use their "
            "server-resolved run subject. "
            "`--raw-result` is a literal string; `--qa-kind` defaults "
            "to the requirement's kind (mismatch is a hard error). "
            "For multi-line evidence, read the file and pass the literal "
            "content through `--raw-result`."
        ),
    },
    {
        "topic": "qa",
        "purpose": "Execute an item's materialized QA plans in snapshot order",
        "recipe": (
            "yoke qa plan run --item PREFIX-N --transition TRANSITION "
            "--base-url https://preview.example"
        ),
        "notes": (
            "Begins or resumes a server-authorized execution before any "
            "local executor runs. Stage pins the immutable roster, digest, "
            "durable cursor, actor/session owner, and any machine lease; "
            "each canonical result advances that cursor. After capture, "
            "agent-verdict cases produce one immutable review bundle and "
            "state=awaiting_agent_review; exit 12 requires the harness to "
            "dispatch the returned typed reviewer contract and submit its "
            "complete verdict batch. Only agent inconclusive creates human "
            "Inbox work. Waiting runs resume from the same cursor, while "
            "completion or abort releases the lease. Hosted services never "
            "resolve local executor credentials."
        ),
    },
    {
        "topic": "qa",
        "purpose": (
            "Execute a named project plan on its real deployment-run subject "
            "(never a synthetic item or host_control bypass)"
        ),
        "recipe": (
            "yoke qa plan run --deployment-run-id RUN "
            "--plan installer-campaign --project yoke"
        ),
    },
    {
        "topic": "qa",
        "purpose": "Execute one materialized Browser method case",
        "recipe": (
            "yoke qa case run --requirement-id R "
            "--base-url https://preview.example "
            "--expected-branch BRANCH --expected-sha SHA"
        ),
        "notes": (
            "The shared case runner authorizes and fetches the immutable "
            "snapshot through qa.case_execution.begin before local work, "
            "executes only requirement R, and owns qa.run.add / "
            "qa.run.complete / qa.artifact.add evidence writes. An active "
            "item claim and ambient session are required. browser-check "
            "decides automatically; "
            "browser-inspection records inconclusive evidence and creates "
            "a review request. Item-backed cases require the active item "
            "claim; deployment-run cases require project permission and the "
            "bound execution session. Never add a parallel Browser run "
            "manually."
        ),
    },
    {
        "topic": "qa",
        "purpose": "Preview the reviewed-implementation gate verdict",
        "recipe": (
            "yoke qa gate-summary --item PREFIX-N --target reviewed-implementation"
        ),
        "notes": (
            "Registered read qa.gate_summary.run. Use --item for a standalone "
            "issue, or --epic-id E --task-num K for an epic task. The summary "
            "is diagnostic only — even with passing tests, route via "
            "`/yoke advance PREFIX-N reviewed-implementation` (never raw items "
            "update) so the gate runs and claim handoff fires."
        ),
    },
    {
        "topic": "qa",
        "purpose": "Summarize unsatisfied QA requirements (read-only)",
        "recipe": (
            "yoke qa gate-summary "
            "--item PREFIX-N --target {reviewed-implementation,implemented}"
        ),
        "notes": (
            "Registered read qa.gate_summary.run (works over https — "
            "replaces the checkout-shaped db_router gate-summary "
            "agent leg). Diagnostic only — never mutates "
            "qa_runs/qa_requirements. Run before /yoke advance "
            "reviewed-implementation or /yoke polish to see which "
            "blocking requirements still need passing runs. Use "
            "--epic-id E --task-num K for epic tasks; the bare call "
            "prints the summary JSON."
        ),
    },
    {
        "topic": "qa",
        "purpose": "Inspect events for an item (canonical agent shape)",
        "recipe": ("yoke events query --item PREFIX-N --limit 20"),
        "notes": (
            "Add `--event-name X`, `--since ISO|'2 hours ago'`, "
            "`--until ...` for narrowing; `--session S "
            "--current-episode` bounds to the current session episode "
            "(fails closed without `--session`). Siblings: `yoke "
            "events tail --limit 20` (zero-config recent slice), "
            "`yoke events count`, `yoke events anomalies`."
        ),
    },
    {
        "topic": "qa",
        "purpose": "Epic dispatch chain (list / advance / inspect)",
        "recipe": (
            "yoke epic-tasks list --epic 1704\n"
            "yoke workflow-item epic-task body-get --epic 1704 "
            "--task-num 5\n"
            "yoke workflow-item epic-dispatch-chain list --epic 1704\n"
            "yoke workflow-item epic-dispatch-chain get --epic 1704 "
            "--worktree branch-name"
        ),
        "notes": (
            "Task list + body reads are wrapped (epic_tasks.list.run / "
            "workflow_item.epic_task.body_get). Dispatch-chain reads use "
            "workflow_item.epic_dispatch_chain.list/get. Epic id is bare "
            "integer. Task num is 1-based."
        ),
    },
]
