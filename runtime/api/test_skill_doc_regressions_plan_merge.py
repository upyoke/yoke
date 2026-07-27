"""Recipe regressions for normalized generated-task reads in plan and merge."""

from runtime.api.skill_doc_regressions_test_helpers import SKILLS, _read


def test_plan_reuses_the_pinned_numeric_item_id_for_generated_tasks() -> None:
    text = _read(SKILLS / "plan" / "SKILL.md")

    assert '_plan_item_id=$(printf \'%s\' "$_plan_pin_json"' in text
    assert '["result"]["item_id"]' in text
    assert "remembered workflow\nnames" in text
    assert "yoke items list --workflow epic" not in text
    assert "yoke items list --workflow issue" not in text
    assert 'yoke epic-tasks list --epic "$_plan_item_id"' in text
    assert 'yoke workflow-item epic-task remove --epic "$_plan_item_id"' in text
    assert (
        'yoke workflow-item epic-task body-get --epic\n'
        '  "$_plan_item_id" --task-num N'
    ) in text
    assert "{N-from-YOK-if-provided}" not in text
    assert "epic_id={epic-id}'" not in text
    assert '--epic "{epic-id}"' not in text


def test_merge_argument_validation_resolves_before_epic_task_reads() -> None:
    text = _read(SKILLS / "merge" / "argument-validation.md")

    resolve = text.index('_epic_id=$(yoke items get "$_epic_ref" id')
    task_read = text.index('yoke epic-tasks list --epic "$_epic_id"')
    assert resolve < task_read
    assert "SELECT COUNT(*) FROM epic_tasks" not in text
    assert "epic_id={epic-id}'" not in text


def test_merge_preflight_reuses_registered_epic_task_rows() -> None:
    text = _read(SKILLS / "merge" / "preflight.md")

    assert 'simulation-get --epic "$_epic_id"' in text
    assert 'yoke epic-tasks list --epic "$_epic_id"' in text
    assert 'yoke items get "$_epic_ref" worktree_plan' in text
    assert "SELECT task_num, title, status FROM epic_tasks" not in text
    assert "SELECT DISTINCT worktree FROM epic_tasks" not in text
    assert "epic_id={epic-id}'" not in text
