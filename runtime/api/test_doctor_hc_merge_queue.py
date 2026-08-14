"""Merge-queue binding health check verdicts."""

from runtime.api.merge_queue_doctor_test_helpers import (
    FakeConn,
    WORKFLOW_COMMENT_ONLY_MERGE_GROUP,
    declared,
    live_rules,
    run,
)
from yoke_core.domain.project_github_auth import ProjectGithubAuthError
from yoke_core.engines import doctor_hc_merge_queue as hc_mod
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def test_undeclared_capability_skips(monkeypatch):
    result = run(
        monkeypatch,
        conn=FakeConn(declares=False),
        rules_body=[],
    )
    assert result.result == "SKIP"
    assert "does not declare" in result.detail


def test_declared_with_rule_and_trigger_passes(monkeypatch):
    result = run(
        monkeypatch,
        conn=FakeConn(),
        rules_body=live_rules(),
    )
    assert result.result == "PASS", result.detail
    assert "merge_queue rule active" in result.detail
    assert "yoke-ci.yml" in result.detail
    assert "parameter drift not checked" in result.detail


def test_declared_without_rule_fails(monkeypatch):
    result = run(
        monkeypatch,
        conn=FakeConn(),
        rules_body=[{"type": "pull_request"}],
    )
    assert result.result == "FAIL"
    assert "no merge_queue rule" in result.detail


def test_missing_trigger_fails_even_when_comment_mentions_merge_group(
    monkeypatch,
):
    result = run(
        monkeypatch,
        conn=FakeConn(),
        rules_body=live_rules(),
        workflow_text=WORKFLOW_COMMENT_ONLY_MERGE_GROUP,
    )
    assert result.result == "FAIL"
    assert "no merge_group trigger" in result.detail


def test_auth_unavailable_skips(monkeypatch):
    def failing_auth(project, db_path=None, required_permissions=None):
        raise ProjectGithubAuthError(project, "no installation")

    monkeypatch.setattr(hc_mod, "resolve_project_github_auth", failing_auth)
    rec = RecordCollector()
    hc_mod.hc_merge_queue_binding(
        FakeConn(), DoctorArgs(project="yoke"), rec
    )
    result = rec.results[-1]
    assert result.result == "SKIP"
    assert "auth unavailable" in result.detail


def test_parameter_drift_fails_when_declaration_present(monkeypatch):
    result = run(
        monkeypatch,
        conn=FakeConn(),
        rules_body=live_rules(grouping="ALLGREEN"),
        declaration=declared(),
    )
    assert result.result == "FAIL"
    assert "merge_queue parameters drifted" in result.detail


def test_declaration_match_passes(monkeypatch):
    result = run(
        monkeypatch,
        conn=FakeConn(),
        rules_body=live_rules(),
        declaration=declared(),
        allow_auto_merge=True,
    )
    assert result.result == "PASS"
    assert "matches .yoke/merge-queue.json" in result.detail


def test_repo_declaration_diffs_parameters_without_checkout(monkeypatch):
    result = run(
        monkeypatch,
        conn=FakeConn(),
        rules_body=live_rules(grouping="ALLGREEN"),
        repo_declaration=declared(),
    )
    assert result.result == "FAIL"
    assert "merge_queue parameters drifted" in result.detail


def test_repo_declaration_match_passes_without_checkout(monkeypatch):
    result = run(
        monkeypatch,
        conn=FakeConn(),
        rules_body=live_rules(),
        repo_declaration=declared(),
    )
    assert result.result == "PASS"
    assert "matches .yoke/merge-queue.json" in result.detail
    assert "upyoke/yoke@main:.yoke/merge-queue.json" in result.detail


def test_malformed_repo_declaration_fails(monkeypatch):
    result = run(
        monkeypatch,
        conn=FakeConn(),
        rules_body=live_rules(),
        repo_body="{not json",
    )
    assert result.result == "FAIL"
    assert "declaration unreadable" in result.detail


def test_json_null_declaration_is_unreadable_not_absent(monkeypatch):
    result = run(
        monkeypatch,
        conn=FakeConn(),
        rules_body=live_rules(),
        repo_body=None,
    )
    assert result.result == "FAIL"
    assert "declaration unreadable" in result.detail
    assert "parameter drift not checked" not in result.detail


def test_checkout_declaration_wins_over_repo(monkeypatch):
    stale = declared()
    stale["ruleset"]["rules"][0]["parameters"]["grouping_strategy"] = (
        "ALLGREEN"
    )
    result = run(
        monkeypatch,
        conn=FakeConn(),
        rules_body=live_rules(),
        declaration=declared(),
        repo_declaration=stale,
    )
    assert result.result == "PASS"
    assert ".yoke/merge-queue.json" in result.detail


def test_allow_auto_merge_drift_fails(monkeypatch):
    result = run(
        monkeypatch,
        conn=FakeConn(),
        rules_body=live_rules(),
        declaration=declared(),
        allow_auto_merge=False,
    )
    assert result.result == "FAIL"
    assert "allow_auto_merge drifted" in result.detail
