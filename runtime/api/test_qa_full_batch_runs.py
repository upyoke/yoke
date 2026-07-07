"""run-add-batch — bulk QA run insertion in one transaction.

Covers ``cmd_run_add_batch``: happy-path multi-insert, JSON-array contract,
validation rejections (non-array, malformed, missing field, empty), atomic
rollback on insert failure, per-row event emission, the agent-for-browser
guard, and inline artifact creation via ``artifact_path``.
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


class TestRunAddBatch:
    """cmd_run_add_batch: bulk insert in one transaction."""

    def _seed_requirement(self, db_path, capsys, item_id=100, qa_kind="ac_verification"):
        req_id = qa.cmd_requirement_add(
            db_path=db_path, item_id=item_id, qa_kind=qa_kind,
            qa_phase="verification", success_policy="test policy",
        )
        capsys.readouterr()
        return req_id

    def test_happy_path_inserts_multiple(self, db_path, capsys, tmp_path):
        req1 = self._seed_requirement(db_path, capsys)
        req2 = self._seed_requirement(db_path, capsys, item_id=200)

        payload = [
            {"requirement_id": req1, "executor_type": "agent", "qa_kind": "ac_verification",
             "verdict": "pass", "raw_result": "All tests pass"},
            {"requirement_id": req2, "executor_type": "agent", "qa_kind": "ac_verification",
             "verdict": "pass", "raw_result": "Verified in output"},
        ]
        json_file = str(tmp_path / "runs.json")
        with open(json_file, "w") as f:
            json.dump(payload, f)

        ids = qa.cmd_run_add_batch(db_path=db_path, json_file=json_file)
        assert len(ids) == 2

        captured = capsys.readouterr()
        parsed = json.loads(captured.out.strip())
        assert parsed == ids

        conn = _conn(db_path)
        for rid in ids:
            row = conn.execute("SELECT * FROM qa_runs WHERE id = %s", (rid,)).fetchone()
            assert row is not None
            assert row["verdict"] == "pass"
        conn.close()

    def test_returns_json_array(self, db_path, capsys, tmp_path):
        req_id = self._seed_requirement(db_path, capsys)

        payload = [
            {"requirement_id": req_id, "executor_type": "agent", "qa_kind": "ac_verification",
             "verdict": "pass", "raw_result": "OK"},
        ]
        json_file = str(tmp_path / "single_run.json")
        with open(json_file, "w") as f:
            json.dump(payload, f)

        ids = qa.cmd_run_add_batch(db_path=db_path, json_file=json_file)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out.strip())
        assert isinstance(parsed, list)
        assert parsed == ids

    def test_rejects_non_array(self, db_path, tmp_path):
        json_file = str(tmp_path / "obj.json")
        with open(json_file, "w") as f:
            json.dump({"requirement_id": 1, "executor_type": "agent", "qa_kind": "smoke"}, f)

        with pytest.raises(SystemExit) as exc:
            qa.cmd_run_add_batch(db_path=db_path, json_file=json_file)
        assert exc.value.code == 2

    def test_rejects_malformed_json(self, db_path, tmp_path):
        json_file = str(tmp_path / "bad.json")
        with open(json_file, "w") as f:
            f.write("{not valid")

        with pytest.raises(SystemExit) as exc:
            qa.cmd_run_add_batch(db_path=db_path, json_file=json_file)
        assert exc.value.code == 2

    def test_rejects_missing_required_field(self, db_path, tmp_path):
        payload = [
            {"executor_type": "agent", "qa_kind": "smoke"},  # missing requirement_id
        ]
        json_file = str(tmp_path / "missing.json")
        with open(json_file, "w") as f:
            json.dump(payload, f)

        with pytest.raises(SystemExit) as exc:
            qa.cmd_run_add_batch(db_path=db_path, json_file=json_file)
        assert exc.value.code == 2

    def test_rejects_empty_array(self, db_path, tmp_path):
        json_file = str(tmp_path / "empty.json")
        with open(json_file, "w") as f:
            json.dump([], f)

        with pytest.raises(SystemExit) as exc:
            qa.cmd_run_add_batch(db_path=db_path, json_file=json_file)
        assert exc.value.code == 2

    def test_rolls_back_on_insert_failure(self, db_path, capsys, tmp_path):
        req_id = self._seed_requirement(db_path, capsys)

        payload = [
            {"requirement_id": req_id, "executor_type": "agent", "qa_kind": "ac_verification",
             "verdict": "pass", "raw_result": "All tests pass"},
            {"requirement_id": req_id, "executor_type": "agent", "qa_kind": "ac_verification",
             "verdict": "not_a_real_verdict", "raw_result": "Should fail"},
        ]
        json_file = str(tmp_path / "rollback.json")
        with open(json_file, "w") as f:
            json.dump(payload, f)

        with pytest.raises(db_backend.integrity_error_types()):
            qa.cmd_run_add_batch(db_path=db_path, json_file=json_file)

        conn = _conn(db_path)
        count = conn.execute("SELECT COUNT(*) FROM qa_runs").fetchone()[0]
        conn.close()
        assert count == 0

    def test_emits_one_event_per_created_run(self, db_path, capsys, tmp_path, monkeypatch):
        req1 = self._seed_requirement(db_path, capsys)
        req2 = self._seed_requirement(db_path, capsys, item_id=200)

        payload = [
            {"requirement_id": req1, "executor_type": "agent", "qa_kind": "ac_verification",
             "verdict": "pass", "raw_result": "All tests pass"},
            {"requirement_id": req2, "executor_type": "agent", "qa_kind": "ac_verification",
             "verdict": "pass", "raw_result": "Verified in output"},
        ]
        json_file = str(tmp_path / "events.json")
        with open(json_file, "w") as f:
            json.dump(payload, f)

        capture_file = tmp_path / "qa-events.jsonl"
        monkeypatch.setenv("YOKE_EVENTS_CAPTURE", "1")
        monkeypatch.setenv("YOKE_EVENTS_FILE", str(capture_file))

        ids = qa.cmd_run_add_batch(db_path=db_path, json_file=json_file)
        capsys.readouterr()

        events = [
            json.loads(line)
            for line in capture_file.read_text().splitlines()
            if line.strip()
        ]
        assert [event["event_name"] for event in events] == [
            "QARunCompleted",
            "QARunCompleted",
        ]
        assert [event["context"]["detail"]["run_id"] for event in events] == ids

    def test_rejects_agent_for_browser_kind(self, db_path, capsys, tmp_path):
        req_id = self._seed_requirement(db_path, capsys, qa_kind="smoke")

        payload = [
            {"requirement_id": req_id, "executor_type": "agent", "qa_kind": "browser_smoke",
             "verdict": "pass"},
        ]
        json_file = str(tmp_path / "browser.json")
        with open(json_file, "w") as f:
            json.dump(payload, f)

        with pytest.raises(SystemExit) as exc:
            qa.cmd_run_add_batch(db_path=db_path, json_file=json_file)
        assert exc.value.code == 2

    def test_with_artifact_path(self, db_path, capsys, tmp_path):
        req_id = self._seed_requirement(db_path, capsys)

        payload = [
            {"requirement_id": req_id, "executor_type": "agent", "qa_kind": "ac_verification",
             "verdict": "pass", "raw_result": "Screenshot OK",
             "artifact_path": "/tmp/screenshot.png"},
        ]
        json_file = str(tmp_path / "artifact.json")
        with open(json_file, "w") as f:
            json.dump(payload, f)

        ids = qa.cmd_run_add_batch(db_path=db_path, json_file=json_file)
        assert len(ids) == 1

        conn = _conn(db_path)
        art = conn.execute("SELECT * FROM qa_artifacts WHERE qa_run_id = %s", (ids[0],)).fetchone()
        assert art is not None
        handle = json.loads(art["artifact_handle"])
        assert handle == {"backend": "local", "path": "/tmp/screenshot.png"}
        assert art["content_type"] == "image/png"
        conn.close()
