"""Empty method_config is a real correction for contracts that accept it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import qa
from yoke_core.domain.qa_method_config_validation import validate_method_config
from yoke_core.domain.qa_requirement_pass_currency import (
    METHOD_CONFIG_REVISION_KEY,
    has_current_passing_run,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.qa_test_helpers import make_qa_db_file
from runtime.api.test_qa_requirement_config_update import (
    _NEW_STEPS,
    _insert_unstamped_pass,
    _seed_browser_requirement,
    _seed_requirement,
)


@pytest.fixture()
def db_path(tmp_path: Path):
    with make_qa_db_file(tmp_path) as path:
        yield path


def test_passthrough_and_terminal_accept_empty_config() -> None:
    assert validate_method_config("passthrough", {}) == {}
    assert validate_method_config("terminal-check", {}) == {}
    assert validate_method_config("terminal-inspection", {}) == {}


def test_executed_empty_config_does_not_satisfy_later_script(db_path: str) -> None:
    req_id = _seed_requirement(db_path, method_id="browser-check", config={})
    _insert_unstamped_pass(db_path, req_id)
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
    passed = has_current_passing_run(conn, req_id)
    conn.close()
    config = stored if isinstance(stored, dict) else json.loads(stored)
    assert config["steps"][1]["action"] == "wait_for"
    assert config[METHOD_CONFIG_REVISION_KEY] is True
    assert passed is False


def test_browser_update_refuses_empty_config(db_path: str) -> None:
    req_id = _seed_browser_requirement(db_path, steps=_NEW_STEPS)
    with pytest.raises(SystemExit) as exc:
        qa.cmd_requirement_update(req_id, "method_config", "{}", db_path=db_path)
    assert exc.value.code == 2
