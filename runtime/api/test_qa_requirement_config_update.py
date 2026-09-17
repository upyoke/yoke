"""In-place method_config correction preserves history and invalidates stale greens."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import qa
from yoke_core.domain.qa_plan_execution_store import canonical
from yoke_core.domain.qa_requirement_pass_currency import (
    METHOD_CONFIG_FIELD,
    METHOD_CONFIG_REVISION_KEY,
    PRESERVED_JSON_FIELD,
    attach_method_config_snapshot,
    bind_correction_identity,
    has_current_passing_run,
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
_NOW = "2026-04-20T00:00:00Z"


@pytest.fixture()
def db_path(tmp_path: Path):
    with make_qa_db_file(tmp_path) as path:
        yield path


def _seed_requirement(db_path: str, *, method_id: str, config: dict) -> int:
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
        (method_id, json.dumps(config), req_id),
    )
    conn.commit()
    conn.close()
    return req_id


def _seed_browser_requirement(db_path: str, *, steps: list[dict]) -> int:
    return _seed_requirement(
        db_path, method_id="browser-check", config={"steps": steps}
    )


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
            _NOW,
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


class TestAttachMethodConfigSnapshot:
    def test_preserves_non_object_json_array(self) -> None:
        attached = json.loads(
            attach_method_config_snapshot("[1,2]", {"steps": _OLD_STEPS})
        )
        assert attached[PRESERVED_JSON_FIELD] == [1, 2]
        assert attached[METHOD_CONFIG_FIELD]["steps"][0]["action"] == "navigate"

    def test_keeps_existing_start_snapshot(self) -> None:
        first = attach_method_config_snapshot("{}", {"steps": _OLD_STEPS})
        second = attach_method_config_snapshot(first, {"steps": _NEW_STEPS})
        recorded = recorded_method_config(second)
        assert recorded is not None
        assert recorded["steps"][1]["action"] == "assert"

    def test_bind_keeps_marker_through_empty_config(self) -> None:
        marked = bind_correction_identity(
            {"steps": _OLD_STEPS}, canonical({"steps": _NEW_STEPS})
        )
        empty = json.loads(bind_correction_identity(marked, canonical({})))
        restored = json.loads(
            bind_correction_identity(empty, canonical({"steps": _NEW_STEPS}))
        )
        assert empty[METHOD_CONFIG_REVISION_KEY] is True
        assert restored[METHOD_CONFIG_REVISION_KEY] is True


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
        config = stored if isinstance(stored, dict) else json.loads(stored)
        run_row = conn.execute(
            "SELECT verdict, raw_result FROM qa_runs WHERE id = %s", (run_id,)
        ).fetchone()
        extra = conn.execute(
            "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id = %s "
            "AND id <> %s",
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

    def test_same_config_keeps_unstamped_pass(self, db_path: str) -> None:
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
