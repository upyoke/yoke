"""The declared ruleset and the live one, compared before a landing.

The declaration is authoritative and the apply is its only writer, but
nothing forces them together, so the live ruleset can require less than
the repository believes it requires. These pin the two halves that close
that window: a comparison both readers share, and a landing that stops
on a real disagreement while an unreadable GitHub only warns.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from runtime.api.merge_queue_landing_test_helpers import land, wire_happy_path
from yoke_core.domain import merge_queue_drift_gate as gate_mod
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
DECLARED = {
    "schema": 1,
    "repository": {"allow_auto_merge": True},
    "ruleset": {
        "name": "merge-queue-main",
        "rules": [
            {"type": "merge_queue", "parameters": {"merge_method": "MERGE"}},
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": False,
                    "do_not_enforce_on_create": False,
                    "required_status_checks": [{"context": "shard-1"}],
                },
            },
        ],
    },
}


def _live_rules(contexts):
    return [
        {
            "type": "merge_queue",
            "parameters": {"merge_method": "MERGE"},
            "ruleset_id": 20658925,
        },
        {
            "type": "required_status_checks",
            "parameters": {
                "strict_required_status_checks_policy": False,
                "do_not_enforce_on_create": False,
                "required_status_checks": [
                    {"context": name} for name in contexts
                ],
            },
        },
    ]


@pytest.fixture
def rest(monkeypatch):
    """Stub the three REST reads the comparison makes."""
    calls = {"repo": {"allow_auto_merge": True}, "ruleset": {}}

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
        drift_mod, "diff_declared_against_live", lambda *a, **k: [],
    )
    report = compare_declared_against_live(
        DECLARED, owner=OWNER, repo=REPO,
        rules=_live_rules(["shard-1"]), token="t",
    )
    assert report.drifted is False
    assert report.unreadable == ()


def test_a_live_ruleset_requiring_less_than_declared_is_drift(rest):
    report = compare_declared_against_live(
        DECLARED, owner=OWNER, repo=REPO, rules=_live_rules([]), token="t",
    )
    assert report.drifted is True
    assert any("required" in line for line in report.drift)


def test_unreadable_repository_settings_are_not_reported_as_drift(rest):
    rest["repo"] = RestTransportError("502")
    report = compare_declared_against_live(
        DECLARED, owner=OWNER, repo=REPO,
        rules=_live_rules(["shard-1"]), token="t",
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


def test_refusal_names_the_declaration_and_the_command_that_clears_it():
    report = LiveDriftReport(drift=("required checks drifted",))
    message = report.refusal("yoke")
    assert "merge-queue.json" in message
    assert "yoke github merge-queue apply --project yoke" in message
    assert "required checks drifted" in message


class TestLandingGate:
    """What the landing does with each report the comparison can produce."""

    @staticmethod
    def _declare(tmp_path, payload=DECLARED):
        target = tmp_path / ".yoke"
        target.mkdir(parents=True, exist_ok=True)
        (target / "merge-queue.json").write_text(json.dumps(payload))
        return tmp_path

    def test_a_project_with_no_declaration_lands_unblocked(self, tmp_path):
        report = drift_blocking_landing(
            "yoke", checkout=str(tmp_path), branch="main",
        )
        assert report.drifted is False
        assert report.unreadable == ()
        assert report.skip_reason == DRIFT_SKIP_DECLARATION_MISSING

    def test_an_unparseable_declaration_warns_rather_than_blocks(
        self, tmp_path,
    ):
        checkout = self._declare(tmp_path, {"schema": 1, "ruleset": {}})
        report = drift_blocking_landing(
            "yoke", checkout=str(checkout), branch="main",
        )
        assert report.drifted is False
        assert "declaration unreadable" in report.unreadable[0]
        assert report.skip_reason == DRIFT_SKIP_DECLARATION_UNREADABLE

    def test_unresolvable_github_auth_warns_rather_than_blocks(
        self, tmp_path, monkeypatch,
    ):
        from yoke_core.domain import project_github_auth as auth_mod

        checkout = self._declare(tmp_path)

        def _raise(project, **kwargs):
            raise auth_mod.MissingRepoBinding(project, "no repo binding")

        monkeypatch.setattr(
            auth_mod, "resolve_project_github_auth", _raise,
        )
        report = drift_blocking_landing(
            "yoke", checkout=str(checkout), branch="main",
        )
        assert report.drifted is False
        assert "ruleset drift unverified" in report.unreadable[0]
        assert report.skip_reason == DRIFT_SKIP_GITHUB_AUTH_UNRESOLVED

    def test_unreachable_github_is_a_countable_skip(
        self, tmp_path, monkeypatch,
    ):
        from yoke_core.domain import project_github_auth as auth_mod

        checkout = self._declare(tmp_path)
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
            "yoke", checkout=str(checkout), branch="main",
        )

        assert report.drifted is False
        assert report.skip_reason == DRIFT_SKIP_GITHUB_UNREACHABLE

    def test_drift_stops_the_landing_with_the_apply_recipe(
        self, monkeypatch,
    ):
        wire_happy_path(monkeypatch)
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
        self, monkeypatch,
    ):
        wire_happy_path(monkeypatch, landing_states=None)
        monkeypatch.setattr(
            route_mod,
            "drift_check_before_landing",
            lambda *a, **k: LiveDriftReport(unreadable=("GitHub 503",)),
        )
        outcome = land()
        assert "GitHub 503" in outcome.warnings


class TestSkipObservability:
    def test_a_skipped_check_emits_its_machine_readable_reason(
        self, monkeypatch,
    ):
        report = LiveDriftReport(
            skip_reason=DRIFT_SKIP_DECLARATION_MISSING,
            skip_detail="no declaration",
        )
        monkeypatch.setattr(
            gate_mod, "drift_blocking_landing", lambda *a, **k: report,
        )
        seen = {}

        def dispatch(**kwargs):
            seen.update(kwargs)
            return SimpleNamespace(
                success=True, result={"emitted": True}, error=None,
            )

        monkeypatch.setattr(gate_mod, "call_dispatcher", dispatch)
        result = gate_mod.drift_check_before_landing(
            "yoke", checkout="/repo", branch="main", item_id=7,
        )

        assert result is report
        assert seen["function_id"] == "events.emit"
        assert seen["payload"]["name"] == "MergeQueueDriftCheckSkipped"
        assert seen["payload"]["item_id"] == "7"
        assert seen["payload"]["context"]["skip_reason"] == (
            DRIFT_SKIP_DECLARATION_MISSING
        )

    def test_event_write_failure_warns_without_blocking(self, monkeypatch):
        report = LiveDriftReport(
            skip_reason=DRIFT_SKIP_DECLARATION_MISSING,
            skip_detail="no declaration",
        )
        monkeypatch.setattr(
            gate_mod, "drift_blocking_landing", lambda *a, **k: report,
        )
        monkeypatch.setattr(
            gate_mod,
            "call_dispatcher",
            lambda **kwargs: SimpleNamespace(
                success=True,
                result={"emitted": False, "reason": "ledger unavailable"},
                error=None,
            ),
        )

        result = gate_mod.drift_check_before_landing(
            "yoke", checkout="/repo", branch="main", item_id=7,
        )

        assert result.drifted is False
        assert "ledger unavailable" in result.unreadable[-1]


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
