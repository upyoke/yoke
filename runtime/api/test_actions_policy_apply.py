"""Actions policies through merge-queue apply, Doctor drift and the CLI."""

from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from runtime.api.test_actions_policy_declaration import (
    FakePolicies,
    _broad_hand_made,
    _cla_policy,
)
from runtime.api.test_merge_queue_declaration import _declared, _live_rules
from yoke_cli.commands.adapters import github_merge_queue as cli
from yoke_core.domain import actions_policy_apply as policy_apply
from yoke_core.domain import merge_queue_declaration_apply as apply_mod
from yoke_core.domain import merge_queue_live_drift as drift_mod
from yoke_core.domain.gh_rest_transport import RestAuthError


@pytest.fixture
def matching_ruleset(monkeypatch):
    """Live ruleset and auto-merge already match :func:`_declared`."""
    bypass = _declared()["ruleset"]["bypass_actors"]
    for module in (apply_mod.rest, drift_mod.mq_rest):
        monkeypatch.setattr(module, "fetch_branch_rules", lambda *a, **k: _live_rules())
        monkeypatch.setattr(module, "fetch_repository", lambda *a, **k: {"allow_auto_merge": True})
        monkeypatch.setattr(module, "get_ruleset", lambda *a, **k: {"id": 99, "bypass_actors": bypass})
    monkeypatch.setattr(
        apply_mod.rest, "list_rulesets", lambda *a, **k: [{"id": 99, "name": "merge-queue-main"}],
    )


def _apply(declared, *, preview=False):
    return apply_mod.apply_declaration(
        declared, owner="upyoke", repo="yoke", token="tok", preview=preview,
    )


def test_a_declaration_without_policies_leaves_them_unread(monkeypatch, matching_ruleset):
    def _untouched(*a, **k):
        raise AssertionError("Actions policies must stay unmanaged")

    monkeypatch.setattr(apply_mod, "converge_policies", _untouched)
    result = _apply(_declared())
    assert result["actions_policies_managed"] is False
    assert result["changed"] is False


def test_preview_reports_the_policy_plan_with_the_ruleset(monkeypatch, matching_ruleset):
    fake = FakePolicies(monkeypatch, [_broad_hand_made()])
    result = _apply(_declared(actions_policies=[_cla_policy()]), preview=True)
    assert result["actions_policies_managed"] is True
    assert result["changed"] is True
    assert "create actions policy 'cla-pull-request-target'" in result["actions"]
    assert "actions policy 'cla-pull-request-target' is missing live" in result["drift_before"]
    assert fake.writes == []


def test_apply_converges_policies_after_the_ruleset(monkeypatch, matching_ruleset):
    fake = FakePolicies(monkeypatch, [_broad_hand_made()])
    result = _apply(_declared(actions_policies=[_cla_policy()]))
    assert result["changed"] is True
    assert result["remaining_drift"] == []
    assert fake.writes == [("create", "cla-pull-request-target"), ("delete", 12372)]


def _compare(declared):
    return drift_mod.compare_declared_against_live(
        declared, owner="upyoke", repo="yoke", rules=_live_rules(), token="tok",
    )


def test_doctor_reports_policy_drift(monkeypatch, matching_ruleset):
    FakePolicies(monkeypatch, [_broad_hand_made()])
    report = _compare(_declared(actions_policies=[_cla_policy()]))
    assert report.unreadable == ()
    assert report.drift == (
        "actions policy 'cla-pull-request-target' is missing live",
        "live actions policy 'Allow all workflow events (incl. pull_request_target)' "
        "(id=12372) is not declared",
    )


def test_unreadable_policies_are_not_drift(monkeypatch, matching_ruleset):
    FakePolicies(monkeypatch)

    def _hidden(*a, **k):
        raise RestAuthError("Resource not accessible by integration", status=403)

    monkeypatch.setattr(policy_apply.rest, "list_repository_policies", _hidden)
    report = _compare(_declared(actions_policies=[_cla_policy()]))
    assert report.drift == ()
    (line,) = report.unreadable
    assert line.startswith("actions policies unreadable: actions policies unreadable for upyoke/yoke")
    assert "Administration: write" in line


def test_landing_enforcement_ignores_policies():
    declared = _declared(actions_policies=[_cla_policy()])
    assert drift_mod.enforcement_drift(declared, rules=_live_rules()) == ()


@pytest.mark.parametrize(
    "result, notice",
    [({"actions": []}, True), ({"actions": [], "actions_policies_managed": False}, False)],
)
def test_cli_names_a_server_that_cannot_apply_policies(result, notice):
    with patch.object(cli, "dispatch_and_emit", return_value=0) as dispatch:
        assert cli.github_merge_queue_apply(["--project", "yoke"]) == 0
    writer = dispatch.call_args.kwargs["human_writer"]
    stdout, stderr = io.StringIO(), io.StringIO()
    writer(SimpleNamespace(success=True, result=result), stdout, stderr)
    assert (cli.ACTIONS_POLICIES_UNSUPPORTED_NOTICE in stderr.getvalue()) is notice
