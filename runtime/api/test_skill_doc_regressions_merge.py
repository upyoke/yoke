"""Recipe regressions for normalized generated-task reads in merge."""

from runtime.api.skill_doc_regressions_test_helpers import SKILLS, _read


def test_merge_preflight_reuses_registered_rows_without_raw_sql() -> None:
    lanes = _read(SKILLS / "usher" / "merge-arguments.md")
    preflight = _read(SKILLS / "usher" / "merge-preflight.md")

    assert "yoke item-worktrees list PREFIX-N --json" in lanes
    assert "simulation-get --epic PREFIX-N --phase integration --json" in preflight
    assert "any FAIL or unfinished task stops" in preflight
    for text in (lanes, preflight):
        assert "FROM epic_tasks" not in text
        assert "epic_id={epic-id}'" not in text


def test_reviewed_lane_catch_up_stays_at_landing_under_existing_claim() -> None:
    closeout = " ".join(
        _read(SKILLS / "conduct" / "engineer-tester-closeout.md").split()
    )
    assert "lagging main never un-reviews a task" in closeout

    lanes = " ".join(_read(SKILLS / "usher" / "merge-lanes.md").split())
    assert "keeps a reviewed task reviewed under the existing claim" in lanes
    assert "only review FAIL or a real scope or criteria change reopens it" in lanes
