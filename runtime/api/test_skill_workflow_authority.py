"""Shared delivery skills interpret immutable workflow authority."""

from pathlib import Path


ROOT = Path(__file__).parents[2]
SKILLS = ROOT / ".agents" / "skills" / "yoke"


def _read(*parts: str) -> str:
    return (SKILLS.joinpath(*parts)).read_text()


def test_refine_uses_active_binding_and_child_policy() -> None:
    skill = _read("refine", "SKILL.md")
    context = _read("refine", "workflow-context.md")
    combined = skill + context
    for required in (
        "yoke workflows item get",
        "yoke workflows version get",
        "executor_bindings",
        "generated_children",
        "REFINE_SOURCE_STATUS",
        "REFINE_TARGET_STATUS",
        "ITEM_NEXT_EXECUTOR=blitz",
    ):
        assert required in combined
    assert "ITEM_WORKFLOW_ID=epic" not in combined
    assert 'if [ "$ITEM_WORKFLOW_ID"' not in combined


def test_plan_mode_comes_from_pinned_policy() -> None:
    text = _read("plan", "SKILL.md")
    for required in (
        "yoke workflows item get",
        "yoke workflows version get",
        "generated_children=none",
        "generated_children=epic_tasks",
        "parallelism=task_graph",
        "half-open",
    ):
        assert required in text
    for forbidden in (
        "--workflow issue",
        "--workflow epic",
        "Issue mode",
        "Epic mode",
        "Determine plan mode from `workflow_id`",
    ):
        assert forbidden not in text


def test_advance_branches_on_executor_and_lane_policy() -> None:
    skill = _read("advance", "SKILL.md")
    context = _read("advance", "workflow-context.md")
    preflight = _read("advance", "preflight-checks.md")
    finalize = _read("advance", "finalize.md")
    combined = skill + context + preflight + finalize
    for required in (
        "yoke workflows item get",
        "yoke workflows version get",
        "_current_executor",
        "_target_executor",
        "_generated_children",
        "_worktree_policy",
    ):
        assert required in combined
    for forbidden in (
        "_item_workflow_id",
        'if [ "$_workflow_id" = "epic" ]',
        "Skip if `_workflow_id` is `epic`",
        "issue implementation loop",
    ):
        assert forbidden not in combined


def test_usher_merge_selection_uses_pinned_lane_policy() -> None:
    text = _read("usher", "merge.md")
    for required in (
        "yoke workflows item get",
        "yoke workflows version get",
        "_usher_generated_children",
        "_usher_worktree_policy",
        "_usher_parallelism",
        "_usher_current_executor",
    ):
        assert required in text
    assert "_item_workflow_id" not in text
    assert "issue items only" not in text.lower()


def test_conduct_dispatch_has_no_unreachable_item_branch_or_retired_teaching() -> None:
    text = _read("conduct", "dispatch-context-dispatch.md")
    retired_function = "qa.screenshot_" + "evidence.satisfy"
    retired_command = "yoke qa screenshot-" + "evidence satisfy"
    for forbidden in (
        retired_function,
        retired_command,
        'if [ "${_workflow_id}" = "issue" ]',
        "Issue items:",
        "Caller prerequisite:",
    ):
        assert forbidden not in text
    assert "generated_children=epic_tasks" in text
    assert "parallelism=task_graph" in text
