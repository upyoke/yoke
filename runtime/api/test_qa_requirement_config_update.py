"""In-place method_config correction preserves history and invalidates stale greens."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import qa
from yoke_core.domain.qa_requirement_pass_currency import (
    has_current_passing_run,
    is_method_config_correction,
    recorded_method_config,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.qa_test_helpers import make_qa_db_file
from runtime.api.qa_transition_test_support import QA_GATED_TRANSITION

_OLD_STEPS = [
    {"action": "navigate", "route": "/dashboard"},
    {"action": "assert", "target": "[data-old=true]", "check": "visible"},
]
_NEW_STEPS = [
    {"action": "navigate", "route": "/dashboard"},
    {"action": "wait_for", "target": "[data-ready=true]"},
    {"action": "assert", "target": "[data-ready=true]", "check": "visible"},
    {"action": "screenshot", "capture": True},
]


@pytest.fixture()
def db_path(tmp_path: Path):
    with make_qa_db_file(tmp_path) as path:
        yield path


def _seed_browser_requirement(db_path: str, *, steps: list[dict]) -> int:
    req_id = qa.cmd_requirement_add(
        db_path=db_path,
        item_id=42,
        qa_kind="plan_case",
        qa_phase="verification",
        workflow_transition_id=QA_GATED_TRANSITION,
    )
    conn = connect_test_db(db_path)
    conn.execute(
        "UPDATE qa_requirements SET method_id = %s, method_config = %s WHERE id = %s",
        ("browser-check", json.dumps({"steps": steps}), req_id),
    )
    conn.commit()
    conn.close()
    return req_id


def _insert_unstamped_pass(db_path: str, req_id: int) -> tuple[int, str | None]:
    conn = connect_test_db(db_path)
    cur = conn.execute(
        "INSERT INTO qa_runs (qa_requirement_id, performed_by, qa_kind, verdict, "
        "raw_result, created_at) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (
            req_id,
            "browser_substrate",
            "plan_case",
            "pass",
            "legacy capture evidence",
            "2026-04-20T00:00:00Z",
        ),
    )
    run_id = int(cur.fetchone()[0])
    raw = conn.execute(
        "SELECT raw_result FROM qa_runs WHERE id = %s", (run_id,)
    ).fetchone()[0]
    conn.commit()
    conn.close()
    return run_id, raw


def _connect_has_pass(db_path: str, req_id: int) -> bool:
    conn = connect_test_db(db_path)
    try:
        return has_current_passing_run(conn, req_id)
    finally:
        conn.close()


class TestMethodConfigUpdate:
    def test_legacy_unstamped_pass_still_satisfies(self, db_path: str) -> None:
        req_id = _seed_browser_requirement(db_path, steps=_OLD_STEPS)
        _insert_unstamped_pass(db_path, req_id)
        assert _connect_has_pass(db_path, req_id)

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
        run_row = conn.execute(
            "SELECT verdict, raw_result FROM qa_runs WHERE id = %s", (run_id,)
        ).fetchone()
        markers = conn.execute(
            "SELECT raw_result FROM qa_runs WHERE qa_requirement_id = %s "
            "AND id <> %s ORDER BY id",
            (req_id, run_id),
        ).fetchall()
        passed = has_current_passing_run(conn, req_id)
        conn.close()
        config = json.loads(stored)
        assert config["steps"][1]["action"] == "wait_for"
        assert config["steps"][2]["check"] == "visible"
        assert run_row[0] == "pass"
        assert run_row[1] == raw_before
        assert len(markers) == 1
        assert is_method_config_correction(markers[0][0])
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

    def test_frozen_deployment_run_row_refuses_update(self, db_path: str) -> None:
        req_id = _seed_browser_requirement(db_path, steps=_OLD_STEPS)
        conn = connect_test_db(db_path)
        conn.execute(
            "UPDATE qa_requirements SET item_id = NULL, deployment_run_id = %s "
            "WHERE id = %s",
            ("run-20260420-001", req_id),
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
        assert marker_count == 0

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

    def test_same_config_does_not_insert_correction(self, db_path: str) -> None:
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
        assert passed is True

    def test_cli_help_names_method_config(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.main(["requirement-update", "--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "method_config" in out
