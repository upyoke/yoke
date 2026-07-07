"""``qa.cmd_requirement_list`` / ``_get`` / ``_waive`` / ``_update`` —
read paths, waiver lifecycle, and field-update validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import qa
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.qa_test_helpers import (
    make_basic_requirement,
    make_qa_db_file,
)


@pytest.fixture()
def db_path(tmp_path: Path):
    with make_qa_db_file(tmp_path) as path:
        yield path


@pytest.fixture()
def req_id(db_path: str) -> int:
    return make_basic_requirement(db_path)


class TestRequirementList:
    def test_list_all(self, db_path: str) -> None:
        qa.cmd_requirement_add(db_path=db_path, item_id=10, qa_kind="a", qa_phase="verification")
        qa.cmd_requirement_add(db_path=db_path, item_id=20, qa_kind="b", qa_phase="verification")
        lines = qa.cmd_requirement_list(db_path=db_path)
        assert len(lines) == 2

    def test_filter_by_item_id(self, db_path: str) -> None:
        qa.cmd_requirement_add(db_path=db_path, item_id=10, qa_kind="a", qa_phase="verification")
        qa.cmd_requirement_add(db_path=db_path, item_id=20, qa_kind="b", qa_phase="verification")
        lines = qa.cmd_requirement_list(db_path=db_path, item_id=10)
        assert len(lines) == 1
        assert "|a|" in lines[0]

    def test_filter_by_epic_id(self, db_path: str) -> None:
        qa.cmd_requirement_add(db_path=db_path, epic_id=5, task_num=1, qa_kind="e", qa_phase="verification")
        qa.cmd_requirement_add(db_path=db_path, item_id=99, qa_kind="x", qa_phase="verification")
        lines = qa.cmd_requirement_list(db_path=db_path, epic_id=5)
        assert len(lines) == 1


class TestRequirementGet:
    def test_get_existing(self, db_path: str, req_id: int) -> None:
        line = qa.cmd_requirement_get(req_id, db_path=db_path)
        assert line.startswith(str(req_id))
        assert "|unit_test|" in line

    def test_get_missing_exits(self, db_path: str) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_get(9999, db_path=db_path)
        assert exc.value.code == 1


class TestRequirementWaive:
    def test_waive_non_blocking(self, db_path: str) -> None:
        rid = qa.cmd_requirement_add(
            db_path=db_path, item_id=10, qa_kind="unit_test",
            qa_phase="verification", blocking_mode="non_blocking",
        )
        qa.cmd_requirement_waive(rid, "not needed", db_path=db_path)
        conn = connect_test_db(db_path)
        row = conn.execute("SELECT waived_at, waiver_rationale, waiver_source FROM qa_requirements WHERE id = %s", (rid,)).fetchone()
        conn.close()
        assert row[0] is not None  # waived_at set
        assert row[1] == "not needed"
        assert row[2] == "agent"  # default source

    def test_waive_blocking_without_force_exits(self, db_path: str, req_id: int) -> None:
        """Blocking requirements refuse waive without --force."""
        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_waive(req_id, "skip it", db_path=db_path)
        assert exc.value.code == 1

    def test_waive_blocking_with_force(self, db_path: str, req_id: int) -> None:
        qa.cmd_requirement_waive(req_id, "operator decision", db_path=db_path, source="operator", force=True)
        conn = connect_test_db(db_path)
        row = conn.execute("SELECT waiver_rationale, waiver_source FROM qa_requirements WHERE id = %s", (req_id,)).fetchone()
        conn.close()
        assert row[0] == "operator decision"
        assert row[1] == "operator"

    def test_waive_missing_exits(self, db_path: str) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_waive(9999, "reason", db_path=db_path)
        assert exc.value.code == 1

    def test_waive_validates_rationale(self, db_path: str) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_waive(1, "", db_path=db_path)
        assert exc.value.code == 2


class TestRequirementUpdate:
    """AC-1: qa requirement-update mirrors the shape of items update."""

    def test_update_blocking_mode(self, db_path: str, req_id: int) -> None:
        qa.cmd_requirement_update(req_id, "blocking_mode", "non_blocking", db_path=db_path)
        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT blocking_mode FROM qa_requirements WHERE id = %s", (req_id,)
        ).fetchone()
        conn.close()
        assert row[0] == "non_blocking"

    def test_update_target_env(self, db_path: str, req_id: int) -> None:
        qa.cmd_requirement_update(req_id, "target_env", "staging", db_path=db_path)
        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT target_env FROM qa_requirements WHERE id = %s", (req_id,)
        ).fetchone()
        conn.close()
        assert row[0] == "staging"

    def test_update_success_policy_json(self, db_path: str) -> None:
        rid = qa.cmd_requirement_add(
            db_path=db_path,
            item_id=42,
            qa_kind="browser_smoke",
            qa_phase="verification",
            success_policy=json.dumps({
                "type": "browser_scenario",
                "base_url": "https://x.test",
                "steps": [
                    {"action": "navigate", "route": "/"},
                    {"action": "screenshot", "capture": True},
                ],
            }),
        )
        new_policy = json.dumps({
            "type": "browser_scenario",
            "base_url": "https://x.test",
            "steps": [
                {"action": "navigate", "route": "/login"},
                {"action": "delay", "duration": 3000},
                {"action": "screenshot", "capture": True},
            ],
        })
        qa.cmd_requirement_update(rid, "success_policy", new_policy, db_path=db_path)
        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT success_policy FROM qa_requirements WHERE id = %s", (rid,)
        ).fetchone()
        conn.close()
        decoded = json.loads(row[0])
        assert decoded["steps"][0]["route"] == "/login"
        assert decoded["steps"][1]["duration"] == 3000

    def test_update_qa_phase_normalizes_synonyms(self, db_path: str, req_id: int) -> None:
        qa.cmd_requirement_update(req_id, "qa_phase", "post_deploy", db_path=db_path)
        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT qa_phase FROM qa_requirements WHERE id = %s", (req_id,)
        ).fetchone()
        conn.close()
        assert row[0] == "post_deploy"

    def test_update_rejects_qa_kind(self, db_path: str, req_id: int) -> None:
        """AC-1: qa_kind is excluded explicitly — the error must call it out."""
        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_update(req_id, "qa_kind", "browser_smoke", db_path=db_path)
        assert exc.value.code == 2

    def test_update_rejects_unknown_field(self, db_path: str, req_id: int) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_update(req_id, "created_at", "2026-01-01", db_path=db_path)
        assert exc.value.code == 2

    def test_update_rejects_invalid_blocking_mode(self, db_path: str, req_id: int) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_update(req_id, "blocking_mode", "never", db_path=db_path)
        assert exc.value.code == 2

    def test_update_rejects_invalid_qa_phase(self, db_path: str, req_id: int) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_update(req_id, "qa_phase", "whenever", db_path=db_path)
        assert exc.value.code == 2

    def test_update_rejects_malformed_success_policy_for_browser_qa(self, db_path: str) -> None:
        rid = qa.cmd_requirement_add(
            db_path=db_path,
            item_id=42,
            qa_kind="browser_smoke",
            qa_phase="verification",
            success_policy=json.dumps({
                "type": "browser_scenario",
                "base_url": "https://x.test",
                "steps": [
                    {"action": "navigate", "route": "/"},
                    {"action": "screenshot", "capture": True},
                ],
            }),
        )
        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_update(rid, "success_policy", "{not json", db_path=db_path)
        assert exc.value.code == 2

    def test_update_missing_requirement_exits(self, db_path: str) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_update(9999, "target_env", "staging", db_path=db_path)
        assert exc.value.code == 1

    def test_update_emits_qa_requirement_updated_event(
        self, db_path: str, req_id: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        capture_file = tmp_path / "update-events.jsonl"
        monkeypatch.setenv("YOKE_EVENTS_CAPTURE", "1")
        monkeypatch.setenv("YOKE_EVENTS_FILE", str(capture_file))

        qa.cmd_requirement_update(req_id, "target_env", "production", db_path=db_path)

        events = [
            json.loads(line)
            for line in capture_file.read_text().splitlines()
            if line.strip()
        ]
        updated = [e for e in events if e["event_name"] == "QARequirementUpdated"]
        assert len(updated) == 1, events
        detail = updated[0]["context"]["detail"]
        assert detail["field"] == "target_env"
        assert detail["new_value"] == "production"
        assert detail["requirement_id"] == req_id

    def test_update_registered_in_event_registry(self, db_path: str) -> None:
        """AC-17 event registration: QARequirementUpdated must appear in the
        curated events table that populate_registry ensures during its run."""
        from yoke_core.domain import events_crud, populate_registry

        events_crud.cmd_init(db_path=db_path)
        populate_registry._register_curated_events(db_path=db_path)

        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT event_name FROM event_registry WHERE event_name = 'QARequirementUpdated'"
        ).fetchone()
        conn.close()
        assert row is not None, (
            "QARequirementUpdated must be registered in event_registry. "
            "Without registration the emit call silently drops events."
        )

    def test_update_in_curated_events_table(self) -> None:
        """AC-17 event registration: QARequirementUpdated is declared in the
        curated events table in populate_registry (the authoritative list)."""
        from yoke_core.domain.populate_registry import CURATED_EVENTS

        names = {entry[0] for entry in CURATED_EVENTS}
        assert "QARequirementUpdated" in names
