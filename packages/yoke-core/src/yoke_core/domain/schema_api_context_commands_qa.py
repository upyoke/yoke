"""``qa`` topic wrapper-command recipes for the agent-context packet.

Sibling of :mod:`schema_api_context_commands` (which combines per-topic
lists into the canonical ``WRAPPER_COMMANDS``). Holds the ``qa`` topic
entries: QA requirement/run reads, run-verdict recording, gate preview,
gate summary, and the events read recipe.

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
            "--blocking-mode blocking --requirement-source ac_derived"
        ),
        "notes": (
            "Registered write qa.requirement.add — item-claim-gated, "
            "item-attached. ac_verification omits `--success-policy` "
            "by default; stricter policy is "
            "`{\"min_runs\":N,\"min_pass\":N}`. Several rows in one "
            "transaction: pipe a JSON array to `yoke qa requirement "
            "add-batch --item PREFIX-N --stdin`. Epic-task / "
            "deployment-run attachment is operator-debug only: "
            "`python3 -m yoke_core.domain.qa requirement-add "
            "--epic-id E --task-num K ...`."
        ),
    },
    {
        "topic": "qa",
        "purpose": "Add a QA requirement — browser_smoke variant",
        "recipe": (
            "yoke qa requirement add "
            "--item PREFIX-N --qa-kind browser_smoke --qa-phase verification "
            "--blocking-mode blocking --requirement-source ac_derived "
            "--capability-requirements browser-qa "
            "--success-policy '{\"steps\":[{\"action\":\"navigate\","
            "\"route\":\"/login\"},{\"action\":\"screenshot\","
            "\"capture\":true,\"name\":\"login\"}]}'"
        ),
        "notes": (
            "Registered write qa.requirement.add. Browser kinds "
            "(`browser_smoke`, `browser_diff`) REQUIRE "
            "`--success-policy` with the `{\"steps\":[…]}` shape."
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
            "Registered write qa.run.add — item-claim-gated. "
            "`--raw-result` is a literal string; `--qa-kind` defaults "
            "to the requirement's kind (mismatch is a hard error). "
            "For multi-line evidence, read the file and pass the literal "
            "content through `--raw-result`."
        ),
    },
    {
        "topic": "qa",
        "purpose": "Add a QA run verdict — browser_substrate × browser_smoke (file evidence)",
        "recipe": (
            "yoke qa run add "
            "--requirement-id R --executor-type browser_substrate "
            "--qa-kind browser_smoke --verdict pass "
            "--raw-result '{\"status\":\"captured\"}'\n"
            "yoke qa artifact add --requirement-id R --run-id RUN "
            "--artifact-type screenshot --artifact-handle "
            "'{\"backend\":\"local\","
            "\"path\":\"/tmp/browser-evidence/login.png\"}'"
        ),
        "notes": (
            "Registered agent path: `yoke qa run add` records inline "
            "evidence, then `yoke qa artifact add` records screenshot "
            "metadata. Browser kinds reject `--executor-type agent`. "
            "`--execution-status {captured|capture_failed}` is "
            "distinct from the quality `--verdict`."
        ),
    },
    {
        "topic": "qa",
        "purpose": "Preview the reviewed-implementation gate verdict",
        "recipe": (
            "yoke qa gate-summary "
            "--item PREFIX-N --target reviewed-implementation"
        ),
        "notes": (
            "Registered read qa.gate_summary.run. Use --item for a standalone "
            "issue, or --epic-id E --task-num K for an epic task. The summary "
            "is diagnostic only — even with passing tests, route via "
            "`/yoke advance YOK-N reviewed-implementation` (never raw items "
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
        "recipe": (
            "yoke events query --item YOK-N --limit 20"
        ),
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
