"""Installed tool read access never authorizes local writes."""

import pytest

from runtime.api.domain.test_lint_session_cwd_read_shaped_access import (
    _seed_lane,
)
from runtime.api.domain import test_lint_session_cwd_read_shaped_access as fixtures

from yoke_core.domain import lint_session_cwd

conn = fixtures.conn
repo = fixtures.repo


@pytest.mark.parametrize(("template", "target"), [
    ("cp -t ~/.local/bin /tmp/a", "/.local/bin"),
    ("yoke dev run -- touch ~/.local/bin/zz", "/.local/bin/zz"),
    ("cp --target-directory={other} /tmp/a", "/.worktrees/"),
])
def test_local_write_cannot_borrow_installed_tool_read_access(
    conn, repo, template, target,
):
    lane = _seed_lane(conn, repo, session_id="sid-lane")
    other = _seed_lane(conn, repo, session_id="sid-other", item_id=2221)
    verdict = _verdict(template.format(other=other), lane)
    assert not verdict.allow
    if "{other}" in template:
        assert verdict.failure_class in {"scope_mismatch", "foreign_lane"}
        assert str(other) in verdict.reason
    else:
        assert verdict.failure_class == "scope_mismatch"
        assert "/__yoke_relay_home__" + target in verdict.reason
    assert target in verdict.reason


@pytest.mark.parametrize("template", [
    "yoke dev run -- ls ~/.local/bin", "yoke dev run -- pytest {lane}/tests",
    "yoke dev run -- touch {lane}/zz", "cp -t {lane}/sub /tmp/a",
])
def test_installed_tool_reads_and_lane_writes_are_allowed(conn, repo, template):
    lane = _seed_lane(conn, repo, session_id="sid-lane")
    assert _verdict(template.format(lane=lane), lane).allow


def _verdict(command, lane):
    return lint_session_cwd.evaluate_pre_tool_use(
        {"session_id": "sid-lane", "tool_name": "Bash", "cwd": str(lane),
         "tool_input": {"command": command}},
        machine_home="/__yoke_relay_home__",
    )
