"""The declared ruleset and the live one, compared before a landing.

The declaration is authoritative and the apply is its only writer, but
nothing forces them together, so the live ruleset can require less than
the repository believes it requires. These pin the two halves that close
that window: a comparison both readers share, and a landing that stops
on a real disagreement while an unreadable GitHub only warns.
"""

from __future__ import annotations

from runtime.api.merge_queue_live_drift_test_support import (
    DECLARED as DECLARED,
    _live_rules as _live_rules,
)


import json
from types import SimpleNamespace

import pytest

from runtime.api.merge_queue_landing_test_helpers import land, wire_happy_path
from yoke_core.domain import merge_queue_live_drift as drift_mod
from yoke_core.domain import merge_queue_route as route_mod
from yoke_core.domain.gh_rest_transport import (
    RestNotFoundError,
    RestTransportError,
)
from yoke_core.domain.merge_queue_live_drift import (
    DRIFT_SKIP_DECLARATION_MISSING,
    DRIFT_SKIP_DECLARATION_UNREADABLE,
    DRIFT_SKIP_GITHUB_AUTH_UNRESOLVED,
    DRIFT_SKIP_GITHUB_UNREACHABLE,
    LiveDriftReport,
    compare_declared_against_live,
    drift_blocking_landing,
    enforcement_drift,
    live_branch_rules,
)

OWNER = "upyoke"
REPO = "yoke"


@pytest.fixture
def rest(monkeypatch):
    """Stub the three REST reads the comparison makes."""
    calls = {"repo": {"allow_auto_merge": True}, "ruleset": {"bypass_actors": []}}

    def _repo(owner, repo, *, token):
        if isinstance(calls["repo"], Exception):
            raise calls["repo"]
        return calls["repo"]

    def _ruleset(owner, repo, ruleset_id, *, token):
        if isinstance(calls["ruleset"], Exception):
            raise calls["ruleset"]
        return calls["ruleset"]

    monkeypatch.setattr(drift_mod.mq_rest, "fetch_repository", _repo)
    monkeypatch.setattr(drift_mod.mq_rest, "get_ruleset", _ruleset)
    return calls


def test_matching_ruleset_reports_no_drift(rest, monkeypatch):
    monkeypatch.setattr(
        drift_mod,
        "diff_declared_against_live",
        lambda *a, **k: [],
    )
    report = compare_declared_against_live(
        DECLARED,
        owner=OWNER,
        repo=REPO,
        rules=_live_rules(["shard-1"]),
        token="t",
    )
    assert report.drifted is False
    assert report.unreadable == ()


@pytest.mark.parametrize("surface,field", [
    ("repo", "allow_auto_merge"), ("ruleset", "bypass_actors"),
])
def test_hidden_administrative_fields_are_unreadable_not_drift(rest, surface, field):
    rest[surface] = {}
    report = compare_declared_against_live(
        DECLARED, owner=OWNER, repo=REPO,
        rules=_live_rules(["shard-1"]), token="t",
    )
    assert report.drift == ()
    assert any(field in line for line in report.unreadable)
    assert "Administration: write" in report.unreadable[0]
    assert "rerun Doctor" in report.unreadable[0]


def test_a_live_ruleset_requiring_less_than_declared_is_drift(rest):
    report = compare_declared_against_live(
        DECLARED,
        owner=OWNER,
        repo=REPO,
        rules=_live_rules([]),
        token="t",
    )
    assert report.drifted is True
    assert any("required" in line for line in report.drift)


def test_unreadable_repository_settings_are_not_reported_as_drift(rest):
    rest["repo"] = RestTransportError("502")
    report = compare_declared_against_live(
        DECLARED,
        owner=OWNER,
        repo=REPO,
        rules=_live_rules(["shard-1"]),
        token="t",
    )
    assert report.drifted is False
    assert "repository settings unreadable" in report.unreadable[0]


def test_a_branch_with_no_ruleset_reads_as_no_rules_not_an_outage(monkeypatch):
    def _raise(owner, repo, branch, *, token):
        raise RestNotFoundError("404")

    monkeypatch.setattr(drift_mod.mq_rest, "fetch_branch_rules", _raise)
    rules, error = live_branch_rules(OWNER, REPO, "main", token="t")
    assert rules == []
    assert error is None


def test_unreachable_branch_rules_report_an_error_rather_than_empty(monkeypatch):
    def _raise(owner, repo, branch, *, token):
        raise RestTransportError("503")

    monkeypatch.setattr(drift_mod.mq_rest, "fetch_branch_rules", _raise)
    rules, error = live_branch_rules(OWNER, REPO, "main", token="t")
    assert rules is None
    assert "branch rules unreadable" in error


def test_refusal_names_the_declaration_and_the_command_that_clears_it(monkeypatch):
    monkeypatch.setattr(drift_mod, "_drift_recovery", lambda *a, **k: "apply recovery")
    report = LiveDriftReport(drift=("required checks drifted",))
    message = report.refusal("yoke", branch="main")
    assert "merge-queue.json" in message
    assert "apply recovery" in message
    assert "required checks drifted" in message


class TestLandingGate:
    """What the landing does with each report the comparison can produce."""

    @pytest.fixture(autouse=True)
    def remote(self, monkeypatch):
        from yoke_core.domain import project_github_auth as auth_mod
        self.raw = json.dumps(DECLARED)
        monkeypatch.setattr(auth_mod, "resolve_project_github_auth",
                            lambda *a, **k: SimpleNamespace(repo="example/repo", token="t"))
        monkeypatch.setattr(drift_mod.mq_rest, "fetch_file_text", lambda *a, **k: self.raw)

    def test_a_project_with_no_declaration_lands_unblocked(self, tmp_path):
        self.raw = None
        report = drift_blocking_landing(
            "yoke",
            branch="main",
        )
        assert report.drifted is False
        assert report.unreadable == ()
        assert report.skip_reason == DRIFT_SKIP_DECLARATION_MISSING

    def test_an_unparseable_declaration_warns_rather_than_blocks(
        self,
        tmp_path,
    ):
        self.raw = json.dumps({"schema": 1, "ruleset": {}})
        report = drift_blocking_landing(
            "yoke",
            branch="main",
        )
        assert report.drifted is False
        assert "declaration unreadable" in report.unreadable[0]
        assert report.skip_reason == DRIFT_SKIP_DECLARATION_UNREADABLE

    def test_unresolvable_github_auth_warns_rather_than_blocks(
        self,
        tmp_path,
        monkeypatch,
    ):
        from yoke_core.domain import project_github_auth as auth_mod


        def _raise(project, **kwargs):
            raise auth_mod.MissingRepoBinding(project, "no repo binding")

        monkeypatch.setattr(
            auth_mod,
            "resolve_project_github_auth",
            _raise,
        )
        report = drift_blocking_landing(
            "yoke",
            branch="main",
        )
        assert report.drifted is False
        assert "ruleset drift unverified" in report.unreadable[0]
        assert report.skip_reason == DRIFT_SKIP_GITHUB_AUTH_UNRESOLVED

    def test_unreachable_github_is_a_countable_skip(
        self,
        tmp_path,
        monkeypatch,
    ):
        from yoke_core.domain import project_github_auth as auth_mod

        monkeypatch.setattr(
            auth_mod,
            "resolve_project_github_auth",
            lambda *a, **k: SimpleNamespace(repo="upyoke/yoke", token="t"),
        )
        monkeypatch.setattr(
            drift_mod,
            "live_branch_rules",
            lambda *a, **k: (None, "branch rules unreadable: GitHub 503"),
        )

        report = drift_blocking_landing(
            "yoke",
            branch="main",
        )

        assert report.drifted is False
        assert report.skip_reason == DRIFT_SKIP_GITHUB_UNREACHABLE

    @pytest.mark.parametrize("lane_checks", [[], ["shard-1", "new-check"]])
    def test_gate_matches_live_regardless_of_lane_retune(self, tmp_path, monkeypatch, lane_checks):
        from copy import deepcopy
        lane = deepcopy(DECLARED)
        lane["ruleset"]["rules"][1]["parameters"]["required_status_checks"] = [
            {"context": name} for name in lane_checks
        ]
        (tmp_path / ".yoke").mkdir()
        (tmp_path / ".yoke/merge-queue.json").write_text(json.dumps(lane))
        reads = []
        def fetch(*args, ref, **kwargs):
            reads.append(ref)
            return self.raw
        monkeypatch.setattr(drift_mod.mq_rest, "fetch_file_text", fetch)
        monkeypatch.setattr(drift_mod, "live_branch_rules",
                            lambda *a, **k: (_live_rules(["shard-1"]), None))
        report = drift_blocking_landing("project", branch="release/stable")
        assert not report.drifted
        assert not report.skipped
        assert reads == ["release/stable"]

    def test_drift_stops_the_landing_with_the_apply_recipe(
        self,
        monkeypatch,
    ):
        wire_happy_path(monkeypatch)
        monkeypatch.setattr(
            drift_mod, "_drift_recovery", lambda *a, **k: "merge-queue apply",
        )
        monkeypatch.setattr(
            route_mod,
            "drift_check_before_landing",
            lambda *a, **k: LiveDriftReport(drift=("8 required, 16 declared",)),
        )
        outcome = land()
        assert outcome.ok is False
        assert outcome.exit_code == 1
        assert "8 required, 16 declared" in outcome.error
        assert "merge-queue apply" in outcome.error

    def test_an_unverifiable_ruleset_lands_and_carries_the_reason(
        self,
        monkeypatch,
    ):
        wire_happy_path(monkeypatch, landing_states=None)
        monkeypatch.setattr(
            route_mod,
            "drift_check_before_landing",
            lambda *a, **k: LiveDriftReport(unreadable=("GitHub 503",)),
        )
        outcome = land()
        assert "GitHub 503" in outcome.warnings


class TestEnforcementScope:
    """What the landing gate will and will not stop a merge for.

    The Doctor check reports every disagreement. The gate blocks only on
    the surface that decides whether a red check can merge, because the
    rest reads as drift on a token that cannot see it.
    """

    def test_fewer_live_required_checks_than_declared_blocks(self):
        drift = enforcement_drift(DECLARED, rules=_live_rules([]))
        assert any("required_status_checks contexts" in x for x in drift)

    def test_drifted_queue_parameters_block(self):
        rules = _live_rules(["shard-1"])
        rules[0]["parameters"] = {"merge_method": "SQUASH"}
        drift = enforcement_drift(DECLARED, rules=rules)
        assert any("merge_queue parameters" in x for x in drift)

    def test_an_unreadable_allow_auto_merge_does_not_block(self):
        # The live read that produced this on a hosted runtime reported
        # "live allow_auto_merge could not be read" against a repository
        # whose enforcement surface matched exactly.
        assert enforcement_drift(DECLARED, rules=_live_rules(["shard-1"])) == ()

    def test_bypass_actors_are_not_compared_by_the_gate(self):
        rules = _live_rules(["shard-1"])
        drift = enforcement_drift(DECLARED, rules=rules)
        assert not any("bypass_actors" in x for x in drift)
