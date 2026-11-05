"""Main-source destinations stay protected through copy options and dev run."""

from unittest import mock

import pytest

from runtime.api.domain.lint_lane_main_write_shell_redirect_test_support import (
    _bash,
    _seed_lane,
)
from runtime.api.domain import (
    lint_lane_main_write_shell_redirect_test_support as fixtures,
)

from yoke_core.domain import lint_lane_main_write

conn = fixtures.conn
repo = fixtures.repo


@pytest.mark.parametrize("template", [
    "cp -t {repo}/sub /tmp/a", "mv --target-directory={repo}/sub /tmp/a",
    "install -t{repo}/sub /tmp/a", "cp -at {repo}/sub /tmp/a",
    "yoke dev run -- touch {repo}/sub/zz",
    "yoke --env prod dev run --lane {lane} -- touch {repo}/sub/zz",
])
def test_main_write_destination_is_denied(conn, repo, template):
    lane = _seed_lane(conn, repo)
    with mock.patch.object(lint_lane_main_write, "emit_denied"):
        verdict = lint_lane_main_write.evaluate_pre_tool_use(
            _bash(template.format(repo=repo, lane=lane), cwd=str(lane))
        )
    assert not verdict.allow
    assert str(repo / "sub") in verdict.reason
    assert str(lane / "sub") in verdict.reason


@pytest.mark.parametrize("template", [
    "cp a b", "cp -t {lane}/sub /tmp/a",
    "cp -t /tmp/out {repo}/README.md", "yoke dev run -- pytest -q tests",
    "yoke dev run -- touch {lane}/x",
])
def test_legitimate_lane_or_scratch_write_is_allowed(conn, repo, template):
    lane = _seed_lane(conn, repo)
    verdict = lint_lane_main_write.evaluate_pre_tool_use(
        _bash(template.format(repo=repo, lane=lane), cwd=str(lane))
    )
    assert verdict.allow
