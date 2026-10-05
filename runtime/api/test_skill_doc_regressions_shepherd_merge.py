"""Recipe regressions for normalized generated-task reads in Shepherd and merge."""

from runtime.api.skill_doc_regressions_test_helpers import SKILLS, _read


def test_shepherd_reuses_the_pinned_numeric_item_id_for_generated_tasks() -> None:
    entry = _read(SKILLS / "shepherd" / "entry.md")
    handoff = _read(SKILLS / "shepherd" / "plan-handoff.md")

    assert "_item_id=$(printf '%s' \"$_item_pin_json\"" in entry
    assert '["result"]["item_id"]' in entry
    assert "_epic_id=$_item_id" in handoff
    assert 'yoke epic-tasks list --epic "$_epic_id"' in handoff
    assert 'yoke workflow-item epic-task remove --epic "$_epic_id"' in handoff
    assert "_epic_id=$_num" not in handoff
    assert "item_id: $_num" not in handoff
    assert "epic_id={epic-id}'" not in handoff
    assert '--epic "{epic-id}"' not in handoff


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
