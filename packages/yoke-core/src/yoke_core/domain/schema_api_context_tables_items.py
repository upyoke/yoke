"""Backlog `items` table entry for the canonical schema cheat sheet.

Split out of the core topic module because the row's own notes carry the
column disambiguations, ref-resolution rules, and posture-write teaching
that agents most often get wrong.
Pure data only — no I/O or DB connections."""

from __future__ import annotations

from yoke_core.domain.epic_task_membership import MEMBERSHIP_FINALIZED_COLUMN

ITEMS_TABLE: dict[str, dict] = {
    "items": {
        "columns": [
            ("id", "INTEGER"),
            ("title", "TEXT"),
            ("workflow_id", "TEXT"),
            ("workflow_version_id", "INTEGER"),
            ("workflow_posture", "TEXT"),
            (MEMBERSHIP_FINALIZED_COLUMN, "TEXT"),
            ("status", "TEXT"),
            ("priority", "TEXT"),
            ("project_id", "INTEGER"),
            ("project_sequence", "INTEGER"),
            ("github_issue", "TEXT"),
            ("frozen", "INTEGER"),
            ("blocked", "INTEGER"),
            ("blocked_reason", "TEXT"),
            ("deployment_flow", "TEXT"),
            ("deploy_stage", "TEXT"),
            ("source", "TEXT"),
            ("owner", "TEXT"),
            ("created_at", "TEXT"),
            ("updated_at", "TEXT"),
        ],
        "notes": (
            "Backlog row keyed by global bare-integer id for internal joins. "
            "The primary key is `id`; items has NO `item_id` or `public_id` column. "
            "`item_id` is a foreign-key column on OTHER tables. "
            "To resolve a public `PREFIX-N` ref in raw SQL use "
            "`WHERE project_id = <p> AND project_sequence = <n>` "
            "(join `projects` for the prefix); never treat the N from a "
            "public ref as `WHERE id = N` — `id` and `project_sequence` "
            "drift. `WHERE id = <n>` is correct only when the caller "
            "already holds the internal id. Public item refs are "
            "project-scoped: join `items.project_id` to `projects.id` and "
            "render `{projects.public_item_prefix}-{items.project_sequence}` "
            "inside project context; the old item-level project slug field "
            "has been deleted. The GitHub linkage is the single `github_issue` "
            "column — there is no "
            "`github_issue_number` and no `github_url`. "
            "The lifecycle columns are the immutable `workflow_id` / "
            "`workflow_version_id` pin and the current `status`. "
            "`workflow_posture` is the item's selected posture JSON, written "
            "at create and amended afterwards through "
            "`workflows.item_posture.amend` (`yoke workflows item-posture "
            "amend PREFIX-N ...`); wrong guesses: that the create-time "
            "selection is final, and that `yoke qa item-plan attach` can "
            "select verification on an item that has none. "
            f"`{MEMBERSHIP_FINALIZED_COLUMN}` durably records the "
            "generated-task membership snapshot, including an empty set. "
            "There is NO `kind` column on items — the function-call "
            "envelope's `target.kind` discriminator "
            "(`item|epic_task|qa_requirement|session|process`) is the "
            "dispatcher's row-type tag, not an items column. Use "
            "`workflow_id` for the registered workflow identity. "
            "Project authority is `project_id` joined to `projects.id`; "
            "`project_sequence` is the per-project public item number. "
            "items.body is a virtual rendered field (use "
            "`items get PREFIX-N body` or read the structured-field columns "
            "directly): spec, design_spec, technical_plan, worktree_plan, "
            "shepherd_log, shepherd_caveats, test_results, deploy_log, "
            "db_mutation_profile (`items.get.run` nests under "
            "`result.fields`; wrong guess: top-level `db_mutation_profile`), "
            "db_compatibility_attestation, architecture_impact, "
            "resolution, resolution_ref, resolution_comment, "
            "spec_updated_at, spec_updated_by, merged_at, deployed_to. Worktree branches and paths live exclusively in "
            "item_worktrees; task and dispatch rows reference those lanes "
            "through item_worktree_id."
        ),
    },
}

__all__ = ["ITEMS_TABLE"]
