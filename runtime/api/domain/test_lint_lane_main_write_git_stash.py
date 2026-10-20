"""``git stash list`` and ``git stash show`` only read the stash stack.

A lane-holding session that inspects the main checkout's stash with
``git -C <main> stash list`` writes nothing there, so the lane-main-write
guard allows it. Every other stash action still moves main's state and
stays refused.
"""

from __future__ import annotations

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_lane_main_write

SESSION = "sid-stash"
ITEM_ID = 2014


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def lane_and_main(conn, tmp_path):
    main = tmp_path / "repo"
    (main / ".worktrees").mkdir(parents=True)
    register_machine_checkout(tmp_path / "machine-config", main, project_id=1)
    seed_item(
        conn,
        item_id=ITEM_ID,
        branch=f"YOK-{ITEM_ID}",
        status="implementing",
        repo_path=main,
    )
    seed_item_claim(conn, SESSION, item_id=ITEM_ID)
    lane = main / ".worktrees" / f"YOK-{ITEM_ID}"
    lane.mkdir(parents=True)
    return lane, main


def _verdict(command: str, cwd):
    return lint_lane_main_write.evaluate_pre_tool_use(
        {
            "session_id": SESSION,
            "tool_name": "Bash",
            "cwd": str(cwd),
            "tool_input": {"command": command},
        }
    )


def test_stash_list_on_main_is_a_read(lane_and_main) -> None:
    lane, main = lane_and_main
    command = (
        f"git -C {main} stash list | head -0; "
        "git show main:docs/teaching/model/topics/x.json >/dev/null"
    )
    assert _verdict(command, lane).allow is True


def test_stash_show_on_main_is_a_read(lane_and_main) -> None:
    lane, main = lane_and_main
    assert _verdict(f"git -C {main} stash show -p stash@{{0}}", lane).allow is True


@pytest.mark.parametrize("action", ["pop", "drop", "apply", "push", ""])
def test_other_stash_actions_on_main_stay_refused(lane_and_main, action) -> None:
    lane, main = lane_and_main
    command = f"git -C {main} stash {action}".rstrip()
    assert _verdict(command, lane).allow is False
