"""Merge-queue binding health check verdicts."""

import json
from types import SimpleNamespace

from yoke_core.domain.project_github_auth import ProjectGithubAuthError
from yoke_core.engines import doctor_hc_merge_queue as hc_mod
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


class _FakeCursor:
    def __init__(self, value):
        self._value = value

    def fetchone(self):
        return (self._value,)


class _FakeConn:
    """Serve scalar reads keyed by SQL substring."""

    def __init__(self, *, project_id=7, declares=True):
        self._project_id = project_id
        self._declares = declares

    def execute(self, sql, params=()):
        if "FROM projects" in sql and "COALESCE" in sql:
            return _FakeCursor("main")
        if "FROM projects" in sql:
            return _FakeCursor(self._project_id)
        if "project_capabilities" in sql:
            return _FakeCursor(1 if self._declares else 0)
        raise AssertionError(f"unexpected sql: {sql}")


def _auth():
    return SimpleNamespace(token="tok", repo="upyoke/yoke")


def _live_rules(*, grouping="HEADGREEN"):
    return [
        {
            "type": "merge_queue",
            "parameters": {
                "merge_method": "MERGE",
                "grouping_strategy": grouping,
                "min_entries_to_merge": 1,
                "min_entries_to_merge_wait_minutes": 5,
                "max_entries_to_build": 5,
                "max_entries_to_merge": 5,
                "check_response_timeout_minutes": 60,
            },
            "ruleset_id": 99,
        },
        {
            "type": "required_status_checks",
            "parameters": {
                "strict_required_status_checks_policy": False,
                "do_not_enforce_on_create": False,
                "required_status_checks": [
                    {"context": "repo-contracts"},
                    {"context": "container"},
                ],
            },
            "ruleset_id": 99,
        },
    ]


def _declared():
    return {
        "schema": 1,
        "ruleset": {
            "name": "merge-queue-main",
            "target": "branch",
            "enforcement": "active",
            "conditions": {
                "ref_name": {
                    "include": ["refs/heads/main"],
                    "exclude": [],
                }
            },
            "bypass_actors": [
                {
                    "actor_id": 5,
                    "actor_type": "RepositoryRole",
                    "bypass_mode": "always",
                }
            ],
            "rules": [
                {
                    "type": "merge_queue",
                    "parameters": {
                        "merge_method": "MERGE",
                        "grouping_strategy": "HEADGREEN",
                        "min_entries_to_merge": 1,
                        "min_entries_to_merge_wait_minutes": 5,
                        "max_entries_to_build": 5,
                        "max_entries_to_merge": 5,
                        "check_response_timeout_minutes": 60,
                    },
                },
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "strict_required_status_checks_policy": False,
                        "do_not_enforce_on_create": False,
                        "required_status_checks": [
                            {"context": "repo-contracts"},
                            {"context": "container"},
                        ],
                    },
                },
            ],
        },
        "repository": {"allow_auto_merge": True},
    }


def _run(
    monkeypatch,
    *,
    conn,
    rules_body,
    declaration=None,
    repo_declaration=None,
    repo_text=None,
    allow_auto_merge=True,
    bypass_actors=None,
):
    if repo_text is None and repo_declaration is not None:
        repo_text = json.dumps(repo_declaration)
    monkeypatch.setattr(
        hc_mod, "resolve_project_github_auth",
        lambda project, db_path=None, required_permissions=None: _auth(),
    )
    monkeypatch.setattr(
        hc_mod, "_workflow_has_merge_group_trigger",
        lambda conn, token, owner, repo, project_id, ref: (
            True, "yoke-ci.yml"
        ),
    )
    monkeypatch.setattr(
        hc_mod.mq_rest, "fetch_file_text",
        lambda owner, repo, file_path, *, ref, token: repo_text,
    )
    monkeypatch.setattr(
        hc_mod.mq_rest, "fetch_branch_rules",
        lambda *a, **k: list(rules_body),
    )
    monkeypatch.setattr(
        hc_mod.mq_rest, "fetch_repository",
        lambda *a, **k: {"allow_auto_merge": allow_auto_merge},
    )
    monkeypatch.setattr(
        hc_mod.mq_rest, "get_ruleset",
        lambda *a, **k: {
            "id": 99,
            "bypass_actors": bypass_actors if bypass_actors is not None else [
                {
                    "actor_id": 5,
                    "actor_type": "RepositoryRole",
                    "bypass_mode": "always",
                }
            ],
        },
    )
    if declaration is None:
        monkeypatch.setattr(
            hc_mod, "_checkout_declaration",
            lambda conn, args: (
                None, "no source checkout mapped for project"
            ),
        )
    else:
        monkeypatch.setattr(
            hc_mod, "_checkout_declaration",
            lambda conn, args: (declaration, ".yoke/merge-queue.json"),
        )
    rec = RecordCollector()
    hc_mod.hc_merge_queue_binding(conn, DoctorArgs(project="yoke"), rec)
    return rec.results[-1]


def test_undeclared_capability_skips(monkeypatch):
    result = _run(
        monkeypatch,
        conn=_FakeConn(declares=False),
        rules_body=[],
    )
    assert result.result == "SKIP"
    assert "does not declare" in result.detail


def test_declared_with_rule_and_trigger_passes(monkeypatch):
    result = _run(
        monkeypatch,
        conn=_FakeConn(),
        rules_body=_live_rules(),
    )
    assert result.result == "PASS"
    assert "merge_queue rule active" in result.detail
    assert "yoke-ci.yml" in result.detail
    assert "parameter drift not checked" in result.detail


def test_declared_without_rule_fails(monkeypatch):
    result = _run(
        monkeypatch,
        conn=_FakeConn(),
        rules_body=[{"type": "pull_request"}],
    )
    assert result.result == "FAIL"
    assert "no merge_queue rule" in result.detail


def test_missing_trigger_fails(monkeypatch):
    monkeypatch.setattr(
        hc_mod, "resolve_project_github_auth",
        lambda project, db_path=None, required_permissions=None: _auth(),
    )
    monkeypatch.setattr(
        hc_mod, "_workflow_has_merge_group_trigger",
        lambda conn, token, owner, repo, project_id, ref: (
            False, "yoke-ci.yml"
        ),
    )
    monkeypatch.setattr(
        hc_mod.mq_rest, "fetch_branch_rules",
        lambda *a, **k: _live_rules(),
    )
    monkeypatch.setattr(
        hc_mod, "_checkout_declaration",
        lambda conn, args: (None, "no declaration"),
    )
    monkeypatch.setattr(
        hc_mod.mq_rest, "fetch_file_text",
        lambda owner, repo, file_path, *, ref, token: None,
    )
    rec = RecordCollector()
    hc_mod.hc_merge_queue_binding(
        _FakeConn(), DoctorArgs(project="yoke"), rec
    )
    result = rec.results[-1]
    assert result.result == "FAIL"
    assert "no merge_group trigger" in result.detail


def test_auth_unavailable_skips(monkeypatch):
    def failing_auth(project, db_path=None, required_permissions=None):
        raise ProjectGithubAuthError(project, "no installation")

    monkeypatch.setattr(
        hc_mod, "resolve_project_github_auth", failing_auth
    )
    rec = RecordCollector()
    hc_mod.hc_merge_queue_binding(
        _FakeConn(), DoctorArgs(project="yoke"), rec
    )
    result = rec.results[-1]
    assert result.result == "SKIP"
    assert "auth unavailable" in result.detail


def test_parameter_drift_fails_when_declaration_present(monkeypatch):
    result = _run(
        monkeypatch,
        conn=_FakeConn(),
        rules_body=_live_rules(grouping="ALLGREEN"),
        declaration=_declared(),
    )
    assert result.result == "FAIL"
    assert "merge_queue parameters drifted" in result.detail


def test_declaration_match_passes(monkeypatch):
    result = _run(
        monkeypatch,
        conn=_FakeConn(),
        rules_body=_live_rules(),
        declaration=_declared(),
        allow_auto_merge=True,
    )
    assert result.result == "PASS"
    assert "matches .yoke/merge-queue.json" in result.detail


def test_repo_declaration_diffs_parameters_without_checkout(monkeypatch):
    result = _run(
        monkeypatch,
        conn=_FakeConn(),
        rules_body=_live_rules(grouping="ALLGREEN"),
        repo_declaration=_declared(),
    )
    assert result.result == "FAIL"
    assert "merge_queue parameters drifted" in result.detail


def test_repo_declaration_match_passes_without_checkout(monkeypatch):
    result = _run(
        monkeypatch,
        conn=_FakeConn(),
        rules_body=_live_rules(),
        repo_declaration=_declared(),
    )
    assert result.result == "PASS"
    assert "matches .yoke/merge-queue.json" in result.detail
    assert "upyoke/yoke@main:.yoke/merge-queue.json" in result.detail


def test_malformed_repo_declaration_fails(monkeypatch):
    result = _run(
        monkeypatch,
        conn=_FakeConn(),
        rules_body=_live_rules(),
        repo_text="{not json",
    )
    assert result.result == "FAIL"
    assert "declaration unreadable" in result.detail


def test_checkout_declaration_wins_over_repo(monkeypatch):
    stale = _declared()
    stale["ruleset"]["rules"][0]["parameters"]["grouping_strategy"] = (
        "ALLGREEN"
    )
    result = _run(
        monkeypatch,
        conn=_FakeConn(),
        rules_body=_live_rules(),
        declaration=_declared(),
        repo_declaration=stale,
    )
    assert result.result == "PASS"
    assert ".yoke/merge-queue.json" in result.detail


def test_allow_auto_merge_drift_fails(monkeypatch):
    result = _run(
        monkeypatch,
        conn=_FakeConn(),
        rules_body=_live_rules(),
        declaration=_declared(),
        allow_auto_merge=False,
    )
    assert result.result == "FAIL"
    assert "allow_auto_merge drifted" in result.detail
