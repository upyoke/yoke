"""A long data argument does not change the main-write verdict on a real path.

The client fact answers every operand of the command, a quoted sentence
included, so the guard sees the same answer for the real write target with
or without a long ``--evidence`` or query string beside it.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.hook_runner.client_facts import WRITE_TARGETS_KEY
from yoke_contracts.hook_runner.shell_parse import parse_shell
from yoke_core.domain import lint_lane_main_write
from yoke_harness.hooks.client_write_targets import write_targets_fact

SESSION = "sid-long-data"
ITEM_ID = 5628
SENTENCE = ("The resident answered the hook inside its budget. " * 7).strip()
# Commands that only carry the string; ``git commit`` on main is itself a
# main-checkout write and draws its own verdict.
DATA = (
    f"yoke feedback --to universe --evidence '{SENTENCE}'",
    f'yoke db read "SELECT id FROM items WHERE note = \'{SENTENCE}\'"',
    f'printf %s "{SENTENCE}" | yoke say --stdin',
)


@pytest.fixture
def lane_repo(tmp_path):
    repo = tmp_path.resolve() / "repo"
    (repo / ".worktrees").mkdir(parents=True)
    (repo / ".git").mkdir()
    with test_database() as conn:
        register_machine_checkout(tmp_path / "machine-config", repo, project_id=1)
        seed_item(
            conn,
            item_id=ITEM_ID,
            branch=f"YOK-{ITEM_ID}",
            status="implementing",
            repo_path=repo,
        )
        seed_item_claim(conn, SESSION, item_id=ITEM_ID)
        lane = repo / ".worktrees" / f"YOK-{ITEM_ID}"
        lane.mkdir(parents=True)
        yield repo, lane


def _verdict(command: str, cwd: Path):
    payload = {
        "session_id": SESSION,
        "tool_name": "Bash",
        "cwd": str(cwd),
        "tool_input": {"command": command},
    }
    facts = write_targets_fact(payload, parse_shell(command))
    assert WRITE_TARGETS_KEY in str(facts)
    with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
        return lint_lane_main_write.evaluate_pre_tool_use({**payload, **facts})


@pytest.mark.parametrize("data", DATA)
@pytest.mark.parametrize("where", ["main", "lane"])
def test_long_data_argument_keeps_the_real_write_verdict(lane_repo, data, where):
    repo, lane = lane_repo
    root = repo if where == "main" else lane
    write = f"touch {(root / 'src' / 'new.py').as_posix()}"
    plain = _verdict(write, repo)
    with_data = _verdict(f"{data} && {write}", repo)
    assert (plain.allow, plain.reason) == (with_data.allow, with_data.reason)
    assert plain.allow is (where == "lane"), plain.reason
