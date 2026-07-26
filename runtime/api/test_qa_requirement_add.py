"""``qa.cmd_requirement_add`` target validation and optional fields."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import qa
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.qa_test_helpers import make_qa_db_file


@pytest.fixture()
def db_path(tmp_path: Path):
    with make_qa_db_file(tmp_path) as path:
        yield path


class TestRequirementAdd:
    def test_add_with_item_id(self, db_path: str) -> None:
        rid = qa.cmd_requirement_add(
            db_path=db_path,
            item_id=10,
            qa_kind="unit_test",
            qa_phase="verification",
        )
        assert isinstance(rid, int)
        assert rid > 0

    def test_add_with_epic_id(self, db_path: str) -> None:
        rid = qa.cmd_requirement_add(
            db_path=db_path,
            epic_id=5,
            task_num=3,
            qa_kind="integration_test",
            qa_phase="post_deploy",
        )
        assert rid > 0

    def test_add_with_deployment_run_id(self, db_path: str) -> None:
        rid = qa.cmd_requirement_add(
            db_path=db_path,
            deployment_run_id="run-abc",
            qa_kind="smoke_test",
            qa_phase="manual_acceptance",
        )
        assert rid > 0

    def test_missing_qa_kind_exits(self, db_path: str) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_add(
                db_path=db_path,
                item_id=10,
                qa_kind="",
                qa_phase="verification",
            )
        assert exc.value.code == 2

    def test_missing_target_exits(self, db_path: str) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_add(
                db_path=db_path,
                qa_kind="unit_test",
                qa_phase="verification",
            )
        assert exc.value.code == 2

    def test_multiple_targets_exits(self, db_path: str) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_add(
                db_path=db_path,
                item_id=10,
                deployment_run_id="run-abc",
                qa_kind="unit_test",
                qa_phase="verification",
            )
        assert exc.value.code == 2

    def test_epic_id_without_task_num_exits(self, db_path: str) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_add(
                db_path=db_path,
                epic_id=5,
                qa_kind="unit_test",
                qa_phase="verification",
            )
        assert exc.value.code == 2

    def test_browser_smoke_requires_success_policy(self, db_path: str) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_add(
                db_path=db_path,
                item_id=10,
                qa_kind="browser_smoke",
                qa_phase="verification",
            )
        assert exc.value.code == 2

    def test_browser_smoke_validates_steps(self, db_path: str) -> None:
        """Success policy must have a valid steps array."""
        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_add(
                db_path=db_path,
                item_id=10,
                qa_kind="browser_smoke",
                qa_phase="verification",
                success_policy='{"no_steps": true}',
            )
        assert exc.value.code == 2

    def test_browser_smoke_validates_action_in_steps(self, db_path: str) -> None:
        """Each step must have an 'action' field."""
        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_add(
                db_path=db_path,
                item_id=10,
                qa_kind="browser_smoke",
                qa_phase="verification",
                success_policy='{"steps": [{"route": "/"}]}',
            )
        assert exc.value.code == 2

    def test_browser_smoke_with_valid_policy(self, db_path: str) -> None:
        rid = qa.cmd_requirement_add(
            db_path=db_path,
            item_id=10,
            qa_kind="browser_smoke",
            qa_phase="verification",
            success_policy='{"steps": [{"action": "navigate", "route": "/"}, {"action": "screenshot", "capture": true}]}',
        )
        assert rid > 0

    def test_optional_fields_stored(self, db_path: str) -> None:
        rid = qa.cmd_requirement_add(
            db_path=db_path,
            item_id=10,
            qa_kind="unit_test",
            qa_phase="verification",
            target_env="staging",
            blocking_mode="non_blocking",
            requirement_source="ac_derived",
            capability_requirements='{"browser": true}',
            suite_id="suite-abc",
        )
        conn = connect_test_db(rid and db_path)
        row = conn.execute("SELECT target_env, blocking_mode, requirement_source, capability_requirements, suite_id FROM qa_requirements WHERE id = %s", (rid,)).fetchone()
        conn.close()
        assert row[0] == "staging"
        assert row[1] == "non_blocking"
        assert row[2] == "ac_derived"
        assert row[3] == '{"browser": true}'
        assert row[4] == "suite-abc"

    def test_invalid_requirement_source_exits_before_sqlite(self, db_path: str, capsys) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_add(
                db_path=db_path,
                item_id=10,
                qa_kind="unit_test",
                qa_phase="verification",
                requirement_source="agent",
            )

        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "--requirement-source must be one of" in err
        assert "sqlite3.IntegrityError" not in err
        conn = connect_test_db(db_path)
        count = conn.execute("SELECT COUNT(*) FROM qa_requirements").fetchone()[0]
        conn.close()
        assert count == 0

    def test_legacy_aliases_normalize_to_current_vocab(self, db_path: str) -> None:
        rid = qa.cmd_requirement_add(
            db_path=db_path,
            item_id=10,
            qa_kind="review",
            qa_phase="validation",
        )
        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT qa_kind, qa_phase FROM qa_requirements WHERE id = %s",
            (rid,),
        ).fetchone()
        conn.close()
        assert row[0] == "implementation_review"
        assert row[1] == "verification"
