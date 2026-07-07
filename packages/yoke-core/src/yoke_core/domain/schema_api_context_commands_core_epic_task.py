"""``core`` topic — epic-task-scoped recipes for the agent-context packet.

Extracted from :mod:`schema_api_context_commands_core` to keep that
module under the 350-line authored-file cap. Merged into the canonical
``CORE_COMMANDS`` export from the parent module.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations


EPIC_TASK_COMMANDS: list[dict] = [
    {
        "topic": "core",
        "purpose": "Read epic task row / body / simulation",
        "recipe": (
            "yoke workflow-item epic-task get --epic <epic-id> "
            "--task-num <task-num>\n"
            "yoke workflow-item epic-task body-get --epic <epic-id> "
            "--task-num <task-num>\n"
            "yoke workflow-item epic-task simulation-get "
            "--epic <epic-id> --phase integration"
        ),
        "notes": (
            "Bare integer epic id. NOT epic slug. Dispatches "
            "workflow_item.epic_task.get / body_get / simulation_get; "
            "body-get --output-file PATH writes the body to a file for "
            "chained reads."
        ),
    },
    {
        "topic": "core",
        "purpose": "Write epic task body / metadata via CLI adapters",
        "recipe": (
            "yoke workflow-item epic-task body-replace "
            "--epic 1704 --task-num 5 --body-file PATH\n"
            "yoke workflow-item epic-task metadata-update "
            "--epic 1704 --task-num 5 "
            "--fields-json '{\"max_attempts\": 2}'"
        ),
        "notes": (
            "Dispatches workflow_item.epic_task.body_replace and "
            "workflow_item.epic_task.metadata_update. Use `/yoke amend` "
            "for split, reassign, add, or remove operations so claim "
            "checks and sync side effects stay in the orchestrated path."
        ),
    },
    {
        "topic": "core",
        "purpose": "Tester: seed / insert / get review verdict for an epic task",
        "recipe": (
            "yoke workflow-item epic-task review-seed --epic <epic-id> "
            "--task-num <task_num>\n"
            "yoke workflow-item epic-task review-insert --epic <epic-id> "
            "--task-num <task_num> --verdict <pass|fail> --body-file PATH\n"
            "yoke workflow-item epic-task review-get --epic <epic-id> "
            "--task-num <task_num>"
        ),
        "notes": (
            "Dispatches workflow_item.epic_task.review_seed / "
            "review_insert / review_get (review_list adds --limit for "
            "history). `review-insert` reads the review body (verdict "
            "rationale, evidence, failing-test traces) from `--body-file "
            "PATH`; --verdict accepts pass or fail (case-insensitive). "
            "Workflow: optional `review-seed` first if no row exists, "
            "then `review-insert`, then `review-get` to verify. Writes "
            "verify the epic work claim; reads need no claim."
        ),
    },
    {
        "topic": "core",
        "purpose": "Engineer: append a progress note to an epic task",
        "recipe": (
            "yoke workflow-item epic-progress-note append "
            "--epic 1704 --task-num 5 --note-num 3 --body-file PATH\n"
            "yoke workflow-item epic-progress-note list "
            "--epic 1704 --task-num 5 --limit 10\n"
            "yoke workflow-item epic-task submission-receipt-get "
            "--epic 1704 --task-num 5 --after-note-count 2"
        ),
        "notes": (
            "The append adapter accepts --body-file PATH, preferred over "
            "stdin. note_num is monotonically increasing per (epic, task); "
            "inspect the current high-water mark with "
            "submission-receipt-get or the progress-note list."
        ),
    },
    {
        "topic": "core",
        "purpose": "Update epic-task status / metadata field via CLI",
        "recipe": (
            "yoke workflow-item epic-task update-status --epic <epic-id> "
            "--task-num <task_num> --status <status>\n"
            "yoke workflow-item epic-task metadata-update "
            "--epic <epic-id> --task-num <task_num> "
            "--fields-json '{\"max_attempts\": 2}'"
        ),
        "notes": (
            "`update-status` dispatches workflow_item.epic_task."
            "update_status (epic work claim required; syncs the GitHub "
            "label) and accepts the lifecycle vocabulary: planning, "
            "plan-drafted, planned, implementing, "
            "reviewing-implementation, reviewed-implementation, "
            "polishing-implementation, implemented, release, done, "
            "blocked, stopped. Terminal success statuses are "
            "pipeline-owned and refused (`pipeline_required`). "
            "`metadata-update` writes selected epic_tasks fields; valid "
            "fields include title, worktree, "
            "context_estimate, dependencies, status, dispatch_attempts, "
            "body, github_issue, branch, worktree_path, blocked_by, "
            "max_attempts, agent_id, last_heartbeat. For body content "
            "prefer `yoke workflow-item epic-task body-replace`; "
            "for status changes from a skill, prefer the "
            "orchestrator-routed transition (e.g. "
            "`yoke conduct epic-task update-status`) so the gate + "
            "cascade fire."
        ),
    },
    {
        "topic": "core",
        "purpose": "Read or refresh an epic dispatch chain",
        "recipe": (
            "yoke workflow-item epic-dispatch-chain list --epic <epic-id>\n"
            "yoke workflow-item epic-dispatch-chain get "
            "--epic <epic-id> --worktree <branch>\n"
            "yoke workflow-item epic-dispatch-chain refresh-activation "
            "--epic <epic-id> --worktree <branch> --task-num <task_num>"
        ),
        "notes": (
            "Dispatches workflow_item.epic_dispatch_chain.*. Reads need no "
            "claim; update / refresh-activation require the epic work claim."
        ),
    },
]


__all__ = ["EPIC_TASK_COMMANDS"]
