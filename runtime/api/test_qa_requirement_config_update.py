"""In-place method_config correction preserves history and invalidates stale greens."""

from __future__ import annotations

from runtime.api.qa_requirement_config_update_test_support import (
    _NEW_STEPS as _NEW_STEPS,
    _NOW as _NOW,
    _OLD_STEPS as _OLD_STEPS,
    _insert_unstamped_pass as _insert_unstamped_pass,
    _seed_browser_requirement as _seed_browser_requirement,
    _seed_requirement as _seed_requirement,
    db_path as db_path,
)


import json

import pytest

from yoke_core.domain import qa
from yoke_core.domain.qa_requirement_pass_currency import (
    METHOD_CONFIG_REVISION_KEY,
    has_current_passing_run,
    recorded_method_config,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.qa_transition_test_support import QA_GATED_TRANSITION


def _connect_has_pass(db_path: str, req_id: int) -> bool:
    conn = connect_test_db(db_path)
    try:
        return has_current_passing_run(conn, req_id)
    finally:
        conn.close()


class TestMethodConfigUpdate:
    def test_unstamped_pass_cannot_prove_executable_config(self, db_path: str) -> None:
        req_id = _seed_browser_requirement(db_path, steps=_OLD_STEPS)
        _insert_unstamped_pass(db_path, req_id)
        assert not _connect_has_pass(db_path, req_id)

    def test_update_keeps_historical_run_and_rejects_stale_green(
        self, db_path: str
    ) -> None:
        req_id = _seed_browser_requirement(db_path, steps=_OLD_STEPS)
        run_id, raw_before = _insert_unstamped_pass(db_path, req_id)
        qa.cmd_requirement_update(
            req_id,
            "method_config",
            json.dumps({"steps": _NEW_STEPS}),
            db_path=db_path,
        )
        conn = connect_test_db(db_path)
        stored = conn.execute(
            "SELECT method_config FROM qa_requirements WHERE id = %s", (req_id,)
        ).fetchone()[0]
        config = stored if isinstance(stored, dict) else json.loads(stored)
        run_row = conn.execute(
            "SELECT verdict, raw_result FROM qa_runs WHERE id = %s", (run_id,)
        ).fetchone()
        extra = conn.execute(
            "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id = %s AND id <> %s",
            (req_id, run_id),
        ).fetchone()[0]
        passed = has_current_passing_run(conn, req_id)
        conn.close()
        assert config["steps"][1]["action"] == "wait_for"
        assert config["steps"][2]["check"] == "visible"
        assert config[METHOD_CONFIG_REVISION_KEY] is True
        assert run_row[0] == "pass"
        assert run_row[1] == raw_before
        assert extra == 0
        assert passed is False

    def test_fresh_run_after_update_satisfies(self, db_path: str) -> None:
        req_id = _seed_browser_requirement(db_path, steps=_OLD_STEPS)
        _insert_unstamped_pass(db_path, req_id)
        qa.cmd_requirement_update(
            req_id,
            "method_config",
            json.dumps({"steps": _NEW_STEPS}),
            db_path=db_path,
        )
        qa.cmd_run_add(
            db_path=db_path,
            requirement_id=req_id,
            performed_by="browser_substrate",
            verdict="pass",
            head_sha="b" * 40,
        )
        conn = connect_test_db(db_path)
        latest = conn.execute(
            "SELECT raw_result FROM qa_runs WHERE qa_requirement_id = %s "
            "AND verdict = 'pass' ORDER BY id DESC LIMIT 1",
            (req_id,),
        ).fetchone()[0]
        passed = has_current_passing_run(conn, req_id)
        conn.close()
        recorded = recorded_method_config(latest)
        assert recorded is not None
        assert recorded["steps"][1]["action"] == "wait_for"
        assert passed is True

    def test_inflight_start_snapshot_does_not_prove_later_config(
        self, db_path: str
    ) -> None:
        req_id = _seed_browser_requirement(db_path, steps=_OLD_STEPS)
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=req_id,
            performed_by="browser_substrate",
        )
        qa.cmd_requirement_update(
            req_id,
            "method_config",
            json.dumps({"steps": _NEW_STEPS}),
            db_path=db_path,
        )
        qa.cmd_run_complete(
            db_path=db_path,
            run_id=run_id,
            verdict="pass",
            raw_result=json.dumps({"evidence": "finished after correction"}),
        )
        conn = connect_test_db(db_path)
        raw = conn.execute(
            "SELECT raw_result FROM qa_runs WHERE id = %s", (run_id,)
        ).fetchone()[0]
        passed = has_current_passing_run(conn, req_id)
        extra = conn.execute(
            "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id = %s",
            (req_id,),
        ).fetchone()[0]
        conn.close()
        recorded = recorded_method_config(raw)
        assert recorded is not None
        assert recorded["steps"][1]["action"] == "assert"
        payload = raw if isinstance(raw, dict) else json.loads(raw)
        assert payload["evidence"] == "finished after correction"
        assert extra == 1
        assert passed is False

    def test_unjudged_deployment_run_row_accepts_a_correction(
        self, db_path: str
    ) -> None:
        """A run-bound case nobody has judged is still a case, not a result.

        The freeze protects a recorded acceptance. Before the case has
        answered there is nothing to protect, and this is the only window in
        which a defect that only shows up against the real deployed target
        can be fixed at all.
        """
        req_id = _seed_browser_requirement(db_path, steps=_OLD_STEPS)
        conn = connect_test_db(db_path)
        conn.execute(
            "UPDATE qa_requirements SET item_id = NULL, deployment_run_id = %s "
            "WHERE id = %s",
            ("run-20260420-001", req_id),
        )
        conn.commit()
        conn.close()
        qa.cmd_requirement_update(
            req_id,
            "method_config",
            json.dumps({"steps": _NEW_STEPS}),
            db_path=db_path,
        )
        conn = connect_test_db(db_path)
        after = conn.execute(
            "SELECT method_config FROM qa_requirements WHERE id = %s", (req_id,)
        ).fetchone()[0]
        conn.close()
        stored = after if isinstance(after, dict) else json.loads(after)
        assert stored["steps"] == _NEW_STEPS

    def test_answered_deployment_run_row_refuses_update(self, db_path: str) -> None:
        req_id = _seed_browser_requirement(db_path, steps=_OLD_STEPS)
        conn = connect_test_db(db_path)
        conn.execute(
            "UPDATE qa_requirements SET item_id = NULL, deployment_run_id = %s "
            "WHERE id = %s",
            ("run-20260420-001", req_id),
        )
        # A determinate verdict is what closes the window: the case has now
        # answered, so its snapshot is the acceptance record.
        conn.execute(
            "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,created_at,started_at,completed_at) VALUES (%s,'worktree_run','plan_case','fail',%s,%s,%s)",
            (
                req_id,
                "2026-04-20T00:00:00Z",
                "2026-04-20T00:00:00Z",
                "2026-04-20T00:00:00Z",
            ),
        )
        before = conn.execute(
            "SELECT method_config FROM qa_requirements WHERE id = %s", (req_id,)
        ).fetchone()[0]
        conn.commit()
        conn.close()
        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_update(
                req_id,
                "method_config",
                json.dumps({"steps": _NEW_STEPS}),
                db_path=db_path,
            )
        assert exc.value.code == 2
        conn = connect_test_db(db_path)
        after = conn.execute(
            "SELECT method_config FROM qa_requirements WHERE id = %s", (req_id,)
        ).fetchone()[0]
        marker_count = conn.execute(
            "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id = %s", (req_id,)
        ).fetchone()[0]
        conn.close()
        assert after == before
        assert marker_count == 1

    def test_non_method_requirement_cannot_take_method_config(
        self, db_path: str
    ) -> None:
        req_id = qa.cmd_requirement_add(
            db_path=db_path,
            item_id=42,
            qa_kind="unit_test",
            qa_phase="verification",
            workflow_transition_id=QA_GATED_TRANSITION,
        )
        with pytest.raises(SystemExit) as exc:
            qa.cmd_requirement_update(
                req_id,
                "method_config",
                json.dumps({"steps": _NEW_STEPS}),
                db_path=db_path,
            )
        assert exc.value.code == 2

    def test_same_config_keeps_history_without_borrowing_missing_proof(
        self, db_path: str
    ) -> None:
        req_id = _seed_browser_requirement(db_path, steps=_OLD_STEPS)
        _insert_unstamped_pass(db_path, req_id)
        qa.cmd_requirement_update(
            req_id,
            "method_config",
            json.dumps({"steps": _OLD_STEPS}),
            db_path=db_path,
        )
        conn = connect_test_db(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id = %s", (req_id,)
        ).fetchone()[0]
        passed = has_current_passing_run(conn, req_id)
        conn.close()
        assert count == 1
        assert passed is False

    def test_cli_help_names_method_config(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.main(["requirement-update", "--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "method_config" in out
