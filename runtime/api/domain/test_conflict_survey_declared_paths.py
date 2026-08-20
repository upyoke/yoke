"""Recorded surveys, section-stored budgets, and mid-edit lane work.

Coverage for the three coordination signals a claim-less direct workflow
depends on: another item's recorded Conflict Survey, a File Budget
authored through the section surface rather than into ``items.spec``,
and a lane whose work is edited but not yet committed. Each was invisible
to the scan, so two items could declare the same edit target and both be
told the survey was clear.
"""

from __future__ import annotations

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.conflict_survey import record_conflict_survey, survey_conflicts

from yoke_core.domain.conflict_survey_blockers import git_touched_paths
from yoke_core.domain.file_budget_paths import FILE_BUDGET_SECTION


def _record_survey(conn, *, item_id, paths, integration_target="main"):
    """Record one item's survey so other items can see its declared intent."""
    survey = survey_conflicts(
        conn,
        item_id=item_id,
        touch_paths=paths,
        integration_target=integration_target,
    )
    record_conflict_survey(conn, survey)
    return survey


def _upsert_section(conn, *, item_id, section_name, content):
    conn.execute(
        "INSERT INTO item_sections "
        "(item_id, section_name, content, ordering, source, "
        "created_at, updated_at) "
        "VALUES (%s, %s, %s, 90, 'test', '2026-08-20T00:00:00Z', "
        "'2026-08-20T00:00:00Z')",
        (item_id, section_name, content),
    )
    conn.commit()


class TestRecordedSurveyIsACoordinationSignal:
    """A survey is the only durable intent a claim-less Dash publishes."""

    def test_second_overlapping_survey_does_not_also_report_clear(self, test_db):
        first_id, second_id = 2230, 2231
        shared_path = "app/tests/test_deployment_contract.py"
        insert_item(test_db, id=first_id, workflow_id="dash")
        insert_item(test_db, id=second_id, workflow_id="dash")

        first = _record_survey(test_db, item_id=first_id, paths=[shared_path])
        assert first.clear is True

        second = survey_conflicts(
            test_db, item_id=second_id, touch_paths=[shared_path],
        )

        assert second.clear is False
        blocker = next(row for row in second.blockers if row.kind == "survey_scope")
        assert blocker.owner_item_id == first_id
        assert blocker.path == shared_path
        assert "Conflict Survey" in blocker.detail

    def test_survey_on_another_integration_target_does_not_block(self, test_db):
        first_id, second_id = 2232, 2233
        shared_path = "src/release_only.py"
        insert_item(test_db, id=first_id, workflow_id="dash")
        insert_item(test_db, id=second_id, workflow_id="dash")
        _record_survey(
            test_db,
            item_id=first_id,
            paths=[shared_path],
            integration_target="release/2026.01",
        )

        second = survey_conflicts(
            test_db, item_id=second_id, touch_paths=[shared_path],
        )

        assert second.clear is True

    def test_terminal_item_survey_stops_coordinating(self, test_db):
        first_id, second_id = 2234, 2235
        shared_path = "src/finished_scope.py"
        insert_item(test_db, id=first_id, workflow_id="dash", status="done")
        insert_item(test_db, id=second_id, workflow_id="dash")
        _record_survey(test_db, item_id=first_id, paths=[shared_path])

        second = survey_conflicts(
            test_db, item_id=second_id, touch_paths=[shared_path],
        )

        assert second.clear is True

    def test_frozen_item_survey_is_dormant(self, test_db):
        first_id, second_id = 2242, 2243
        shared_path = "src/parked_scope.py"
        insert_item(test_db, id=first_id, workflow_id="dash", frozen=1)
        insert_item(test_db, id=second_id, workflow_id="dash")
        _record_survey(test_db, item_id=first_id, paths=[shared_path])

        second = survey_conflicts(
            test_db, item_id=second_id, touch_paths=[shared_path],
        )

        assert second.clear is True

    def test_coordination_only_edge_clears_a_survey_overlap(self, test_db):
        first_id, second_id = 2236, 2237
        shared_path = "src/independently_edited.py"
        insert_item(test_db, id=first_id, workflow_id="dash")
        insert_item(test_db, id=second_id, workflow_id="dash")
        _record_survey(test_db, item_id=first_id, paths=[shared_path])
        test_db.execute(
            "INSERT INTO item_dependencies "
            "(dependent_item_id, blocking_item_id, gate_point, satisfaction, "
            "source, rationale, created_at) VALUES (%s, %s, "
            "'coordination_only', 'fact:merged', 'test', %s, "
            "'2026-08-20T00:00:00Z')",
            (
                second_id,
                first_id,
                f"decision=coordination_only. shared_paths={shared_path}. "
                "independence_evidence=disjoint functions",
            ),
        )
        test_db.commit()

        second = survey_conflicts(
            test_db, item_id=second_id, touch_paths=[shared_path],
        )

        assert second.clear is True

    def test_stronger_signal_wins_attribution_over_the_survey(self, test_db):
        first_id, second_id = 2238, 2239
        shared_path = "src/claimed_and_surveyed.py"
        insert_item(test_db, id=first_id, workflow_id="dash")
        insert_item(test_db, id=second_id, workflow_id="dash")
        _record_survey(test_db, item_id=first_id, paths=[shared_path])
        _upsert_section(
            test_db,
            item_id=first_id,
            section_name=FILE_BUDGET_SECTION,
            content=f"- `{shared_path}` — one job\n",
        )

        second = survey_conflicts(
            test_db, item_id=second_id, touch_paths=[shared_path],
        )

        assert {row.kind for row in second.blockers} == {"frontier_scope"}


class TestSectionStoredFileBudget:
    """A budget authored through the section surface never reaches spec."""

    def test_section_stored_budget_is_visible_to_the_scan(self, test_db):
        candidate_id, blocker_id = 2240, 2241
        shared_path = "src/section_budget_only.py"
        insert_item(test_db, id=candidate_id, workflow_id="dash")
        insert_item(test_db, id=blocker_id, workflow_id="issue")
        _upsert_section(
            test_db,
            item_id=blocker_id,
            section_name=FILE_BUDGET_SECTION,
            content=f"### Edit targets\n\n- `{shared_path}` — one job\n",
        )

        survey = survey_conflicts(
            test_db, item_id=candidate_id, touch_paths=[shared_path],
        )

        assert survey.clear is False
        assert {row.kind for row in survey.blockers} == {"frontier_scope"}


class TestWorktreeSignalSeesUncommittedWork:
    """An agent mid-edit is in-flight work, committed or not."""

    def test_uncommitted_and_untracked_paths_are_reported(self, tmp_path):
        import subprocess

        lane = tmp_path / "lane"
        lane.mkdir()

        def run(*argv):
            subprocess.run(
                ["git", "-C", str(lane), *argv], check=True, capture_output=True,
            )

        run("init", "-q", "-b", "main")
        run("config", "user.email", "lane@example.test")
        run("config", "user.name", "Lane")
        (lane / "committed.py").write_text("original\n")
        run("add", "-A")
        run("commit", "-q", "-m", "base")
        (lane / "committed.py").write_text("edited but not committed\n")
        (lane / "brand_new.py").write_text("untracked\n")
        (lane / ".gitignore").write_text("ignored_scratch.log\n")
        (lane / "ignored_scratch.log").write_text("noise\n")

        touched = git_touched_paths(str(lane), "main")

        assert "committed.py" in touched
        assert "brand_new.py" in touched
        assert "ignored_scratch.log" not in touched
