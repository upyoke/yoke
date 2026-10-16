"""Pure-function coverage for the lane-main-write command classifier.

The guard's integration tests own the deny/allow verdict; this sibling
module owns the classifier's own token walk so the integration file
stays under the repo's file-line cap.

Both cases here turn on the same fact: an operator written flush
against the token before it must still end that invocation. Tokenizing
the whole body with ``shlex`` alone glues the operator onto the
preceding word, so a compound reads as a single invocation and the
classifier answers for the leading command instead of for every
command the body actually runs.
"""

from __future__ import annotations

import pytest

from yoke_contracts.hook_runner.client_facts import WRITE_TARGETS_KEY, client_fact
from yoke_core.domain.lint_lane_main_write_classify import (
    is_generated_view_write,
    is_yoke_adapter_command,
    lane_path_exists_on_disk,
)
from yoke_core.domain.session_claimed_worktrees import ClaimedWorktree


@pytest.mark.parametrize(
    "command",
    [
        "yoke items get YOK-1",
        "yoke items get YOK-1; yoke items get YOK-2",
        "yoke items get YOK-1 ; yoke items get YOK-2",
        "yoke items get YOK-1 && yoke lifecycle transition YOK-1 --to done",
    ],
)
def test_every_segment_is_a_yoke_adapter(command):
    assert is_yoke_adapter_command(command)


@pytest.mark.parametrize(
    "command",
    [
        "yoke items get YOK-1; rm -rf /tmp/scratch",
        "yoke items get YOK-1 ; rm -rf /tmp/scratch",
        "yoke items get YOK-1 && git commit -am wip",
        "rm -rf /tmp/scratch; yoke items get YOK-1",
    ],
)
def test_a_non_adapter_segment_disqualifies_the_command(command):
    assert not is_yoke_adapter_command(command)


def test_empty_command_is_not_an_adapter_command():
    assert not is_yoke_adapter_command("")
    assert not is_yoke_adapter_command("   ")


_LANE = ClaimedWorktree(item_id=1, task_num=None, worktree_path="/c/repo/.worktrees/L/")


def _worktrees_fact(worktrees):
    return client_fact(WRITE_TARGETS_KEY, {"paths": {}, "worktrees": worktrees})


def test_lane_counts_as_present_until_the_client_reports_its_worktrees():
    assert lane_path_exists_on_disk({}, _LANE) is True


def test_lane_presence_follows_the_client_worktree_list():
    present = _worktrees_fact(["/c/repo", "/c/repo/.worktrees/L"])
    assert lane_path_exists_on_disk(present, _LANE) is True
    assert lane_path_exists_on_disk(_worktrees_fact(["/c/repo"]), _LANE) is False


def test_generated_view_is_classified_by_path_shape_alone(tmp_path):
    # Nothing exists on disk: the classifier reads no file content.
    root = str(tmp_path / "absent-checkout")
    assert is_generated_view_write(f"{root}/.yoke/BOARD.md", root)
    assert not is_generated_view_write(f"{root}/runtime/api/foo.py", root)
    assert not is_generated_view_write("/elsewhere/runtime/api/foo.py", root)
