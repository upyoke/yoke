"""Drift recovery never applies a stale lane's declaration to shared rules."""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from runtime.api.merge_queue_landing_test_helpers import land, wire_happy_path
from runtime.api.test_merge_queue_live_drift import DECLARED, _live_rules
from yoke_core.domain import merge_queue_live_drift as drift_mod
from yoke_core.domain import merge_queue_route as route_mod
from yoke_core.domain import project_github_auth as auth_mod
from yoke_core.domain.gh_rest_transport import RestTransportError


@pytest.fixture
def gate(monkeypatch):
    state = {"declaration": json.dumps(DECLARED), "rules": _live_rules(["shard-1"])}
    reads = []

    def read_file(owner, repo, path, *, ref, token):
        reads.append((path, ref))
        value = state["declaration"]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(
        auth_mod, "resolve_project_github_auth",
        lambda *a, **k: SimpleNamespace(repo="example/project", token="t"),
    )
    monkeypatch.setattr(drift_mod.mq_rest, "fetch_file_text", read_file)
    monkeypatch.setattr(
        drift_mod, "live_branch_rules", lambda *a, **k: (state["rules"], "rules unavailable"),
    )
    state["reads"] = reads
    return state


def test_stale_lane_gets_update_recovery_when_gate_matches_live(gate, monkeypatch):
    wire_happy_path(monkeypatch)
    monkeypatch.setattr(
        route_mod, "drift_check_before_landing",
        lambda *a, **k: drift_mod.LiveDriftReport(drift=("8 declared; 16 live",)),
    )
    outcome = land()
    assert not outcome.ok
    assert "8 declared; 16 live" in outcome.error
    assert "Update this lane from origin/main, re-verify" in outcome.error
    assert "merge-queue apply" not in outcome.error
    assert gate["reads"] == [(".yoke/merge-queue.json", "main")]


def test_gate_drift_gets_apply_from_gate_checkout(gate):
    gate["rules"] = _live_rules([])
    message = drift_mod.LiveDriftReport(drift=("checks differ",)).refusal(
        "project", branch="main",
    )
    assert "origin/main also differs" in message
    assert "From an up-to-date checkout of main" in message
    assert "yoke github merge-queue apply --project project" in message


def test_gate_branch_is_not_assumed_to_be_main(gate):
    message = drift_mod.LiveDriftReport(drift=("checks differ",)).refusal(
        "project", branch="release/stable",
    )
    assert "Update this lane from origin/release/stable" in message
    assert gate["reads"] == [(".yoke/merge-queue.json", "release/stable")]
    assert "merge-queue apply" not in message


@pytest.mark.parametrize("raw", [None, "not json", '{"schema": 1}', RestTransportError("503")])
def test_unreadable_gate_never_recommends_apply(gate, raw):
    gate["declaration"] = raw
    message = drift_mod.LiveDriftReport(drift=("checks differ",)).refusal(
        "project", branch="main",
    )
    assert "gate_declaration_unverified" in message
    assert "Restore read access and a valid" in message
    assert "merge-queue apply" not in message


def test_unreadable_live_rules_never_recommends_apply(gate):
    gate["rules"] = None
    message = drift_mod.LiveDriftReport(drift=("checks differ",)).refusal(
        "project", branch="main",
    )
    assert "gate_declaration_unverified: rules unavailable" in message
    assert "merge-queue apply" not in message


def test_auth_failure_never_recommends_apply(gate, monkeypatch):
    def unavailable(project, **kwargs):
        raise auth_mod.MissingRepoBinding(project, "no binding")

    monkeypatch.setattr(auth_mod, "resolve_project_github_auth", unavailable)
    message = drift_mod.LiveDriftReport(drift=("checks differ",)).refusal(
        "project", branch="main",
    )
    assert "gate_declaration_unverified" in message
    assert "merge-queue apply" not in message


def test_gate_comparison_uses_enforcement_scope(gate):
    declared = deepcopy(DECLARED)
    declared["repository"]["allow_auto_merge"] = False
    declared["ruleset"]["bypass_actors"] = [{"actor_id": 5}]
    gate["declaration"] = json.dumps(declared)
    message = drift_mod.LiveDriftReport(drift=("checks differ",)).refusal(
        "project", branch="main",
    )
    assert "already matches the live rules" in message
    assert "merge-queue apply" not in message
