"""requirement-add-batch — bulk requirement insertion in one transaction.

Covers ``cmd_requirement_add_batch``: happy-path multi-insert, JSON-array
contract, validation rejections (non-array, malformed, missing field, no
target, empty), atomic rollback on insert failure, per-row event emission,
and epic-task attachment.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import db_backend, qa
from runtime.api.qa_full_test_helpers import conn_with_rows, make_qa_db_file


@pytest.fixture()
def db_path(tmp_path):
    with make_qa_db_file(tmp_path) as path:
        yield path


def _conn(db_path: str):
    return conn_with_rows(db_path)


class TestRequirementAddBatch:
    """cmd_requirement_add_batch: bulk insert in one transaction."""

    def test_happy_path_inserts_multiple(self, db_path, capsys, tmp_path):
        payload = [
            {"item_id": 100, "qa_kind": "ac_verification", "qa_phase": "verification",
             "success_policy": "Test policy A"},
            {"item_id": 100, "qa_kind": "ac_verification", "qa_phase": "verification",
             "success_policy": "Test policy B"},
            {"item_id": 200, "qa_kind": "smoke", "qa_phase": "verification",
             "blocking_mode": "non_blocking", "requirement_source": "seeded_default",
             "success_policy": "Smoke passes"},
        ]
        json_file = str(tmp_path / "reqs.json")
        with open(json_file, "w") as f:
            json.dump(payload, f)

        ids = qa.cmd_requirement_add_batch(db_path=db_path, json_file=json_file)
        assert len(ids) == 3
        assert all(isinstance(i, int) and i > 0 for i in ids)

        captured = capsys.readouterr()
        parsed = json.loads(captured.out.strip())
        assert parsed == ids

        # Verify rows exist in DB
        conn = _conn(db_path)
        for rid in ids:
            row = conn.execute("SELECT * FROM qa_requirements WHERE id = %s", (rid,)).fetchone()
            assert row is not None
        conn.close()

    def test_returns_json_array(self, db_path, capsys, tmp_path):
        payload = [
            {"item_id": 100, "qa_kind": "ac_verification", "qa_phase": "verification",
             "success_policy": "AC check"},
        ]
        json_file = str(tmp_path / "single.json")
        with open(json_file, "w") as f:
            json.dump(payload, f)

        ids = qa.cmd_requirement_add_batch(db_path=db_path, json_file=json_file)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out.strip())
        assert isinstance(parsed, list)
        assert parsed == ids

    def test_rejects_non_array(self, db_path, tmp_path):
        json_file = str(tmp_path / "obj.json")
        with open(json_file, "w") as f:
            json.dump({"item_id": 100, "qa_kind": "smoke", "qa_phase": "verification"}, f)

        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_add_batch(db_path=db_path, json_file=json_file)
        assert exc.value.code == 2

    def test_rejects_malformed_json(self, db_path, tmp_path):
        json_file = str(tmp_path / "bad.json")
        with open(json_file, "w") as f:
            f.write("not json at all")

        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_add_batch(db_path=db_path, json_file=json_file)
        assert exc.value.code == 2

    def test_rejects_missing_required_field(self, db_path, tmp_path):
        payload = [
            {"item_id": 100, "qa_phase": "verification"},  # missing qa_kind
        ]
        json_file = str(tmp_path / "missing.json")
        with open(json_file, "w") as f:
            json.dump(payload, f)

        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_add_batch(db_path=db_path, json_file=json_file)
        assert exc.value.code == 2

    def test_rejects_no_attachment_target(self, db_path, tmp_path):
        payload = [
            {"qa_kind": "smoke", "qa_phase": "verification"},  # no item_id/epic_id/deployment_run_id
        ]
        json_file = str(tmp_path / "no_target.json")
        with open(json_file, "w") as f:
            json.dump(payload, f)

        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_add_batch(db_path=db_path, json_file=json_file)
        assert exc.value.code == 2

    def test_rejects_empty_array(self, db_path, tmp_path):
        json_file = str(tmp_path / "empty.json")
        with open(json_file, "w") as f:
            json.dump([], f)

        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_add_batch(db_path=db_path, json_file=json_file)
        assert exc.value.code == 2

    def test_rolls_back_on_insert_failure(self, db_path, tmp_path):
        payload = [
            {"item_id": 100, "qa_kind": "ac_verification", "qa_phase": "verification",
             "blocking_mode": "blocking", "success_policy": "Test policy A"},
            {"item_id": 100, "qa_kind": "ac_verification", "qa_phase": "verification",
             "blocking_mode": "invalid_mode", "success_policy": "Test policy B"},
        ]
        json_file = str(tmp_path / "rollback.json")
        with open(json_file, "w") as f:
            json.dump(payload, f)

        with pytest.raises(db_backend.integrity_error_types()):
            qa.cmd_requirement_add_batch(db_path=db_path, json_file=json_file)

        conn = _conn(db_path)
        count = conn.execute("SELECT COUNT(*) FROM qa_requirements").fetchone()[0]
        conn.close()
        assert count == 0

    def test_emits_one_event_per_created_requirement(self, db_path, capsys, tmp_path, monkeypatch):
        payload = [
            {"item_id": 100, "qa_kind": "ac_verification", "qa_phase": "verification",
             "success_policy": "Test policy A"},
            {"item_id": 100, "qa_kind": "ac_verification", "qa_phase": "verification",
             "success_policy": "Test policy B"},
        ]
        json_file = str(tmp_path / "events.json")
        with open(json_file, "w") as f:
            json.dump(payload, f)

        capture_file = tmp_path / "qa-events.jsonl"
        monkeypatch.setenv("YOKE_EVENTS_CAPTURE", "1")
        monkeypatch.setenv("YOKE_EVENTS_FILE", str(capture_file))

        ids = qa.cmd_requirement_add_batch(db_path=db_path, json_file=json_file)
        capsys.readouterr()

        events = [
            json.loads(line)
            for line in capture_file.read_text().splitlines()
            if line.strip()
        ]
        assert [event["event_name"] for event in events] == [
            "QARequirementCreated",
            "QARequirementCreated",
        ]
        assert [event["context"]["detail"]["requirement_id"] for event in events] == ids

    def test_epic_task_attachment(self, db_path, capsys, tmp_path):
        payload = [
            {"epic_id": 50, "task_num": 1, "qa_kind": "integration", "qa_phase": "verification",
             "success_policy": "Task integration passes"},
        ]
        json_file = str(tmp_path / "epic.json")
        with open(json_file, "w") as f:
            json.dump(payload, f)

        ids = qa.cmd_requirement_add_batch(db_path=db_path, json_file=json_file)
        assert len(ids) == 1

        conn = _conn(db_path)
        row = conn.execute("SELECT epic_id, task_num FROM qa_requirements WHERE id = %s", (ids[0],)).fetchone()
        assert row["epic_id"] == 50
        assert row["task_num"] == 1
        conn.close()
