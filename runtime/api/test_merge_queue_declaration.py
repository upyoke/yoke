"""Unit tests for declared merge-queue load/diff/apply helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import merge_queue_declaration as decl
from yoke_core.domain import merge_queue_declaration_apply as apply_mod
from yoke_core.domain.gh_rest_transport import RestTransportError


def _declared(**overrides):
    base = {
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
    base.update(overrides)
    return base


def _live_rules(*, grouping="HEADGREEN", contexts=None):
    contexts = contexts or ["container", "repo-contracts"]
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
                    {"context": c} for c in contexts
                ],
            },
            "ruleset_id": 99,
        },
    ]


def test_load_declaration_round_trip(tmp_path: Path):
    path = tmp_path / "merge-queue.json"
    path.write_text(json.dumps(_declared()), encoding="utf-8")
    loaded = decl.load_declaration(path)
    assert loaded["ruleset"]["name"] == "merge-queue-main"
    assert loaded["repository"]["allow_auto_merge"] is True


def test_diff_passes_when_live_matches():
    problems = decl.diff_declared_against_live(
        _declared(),
        live_branch_rules=_live_rules(),
        live_allow_auto_merge=True,
        live_bypass_actors=[
            {
                "actor_id": 5,
                "actor_type": "RepositoryRole",
                "bypass_mode": "always",
            }
        ],
        compare_bypass=True,
    )
    assert problems == []


def test_diff_fails_on_grouping_drift():
    problems = decl.diff_declared_against_live(
        _declared(),
        live_branch_rules=_live_rules(grouping="ALLGREEN"),
        live_allow_auto_merge=True,
    )
    assert any("merge_queue parameters drifted" in p for p in problems)


def test_diff_fails_on_allow_auto_merge_drift():
    problems = decl.diff_declared_against_live(
        _declared(),
        live_branch_rules=_live_rules(),
        live_allow_auto_merge=False,
    )
    assert any("allow_auto_merge drifted" in p for p in problems)


def test_apply_is_idempotent_when_already_matched(monkeypatch):
    calls = {"create": 0, "update": 0, "patch": 0}

    monkeypatch.setattr(
        apply_mod.rest, "list_rulesets",
        lambda *a, **k: [{"id": 99, "name": "merge-queue-main"}],
    )
    monkeypatch.setattr(
        apply_mod.rest, "fetch_branch_rules",
        lambda *a, **k: _live_rules(),
    )
    monkeypatch.setattr(
        apply_mod.rest, "fetch_repository",
        lambda *a, **k: {"allow_auto_merge": True},
    )
    monkeypatch.setattr(
        apply_mod.rest, "get_ruleset",
        lambda *a, **k: {
            "id": 99,
            "name": "merge-queue-main",
            "bypass_actors": [
                {
                    "actor_id": 5,
                    "actor_type": "RepositoryRole",
                    "bypass_mode": "always",
                }
            ],
            "rules": _declared()["ruleset"]["rules"],
        },
    )

    def _create(*a, **k):
        calls["create"] += 1
        return {"id": 99}

    def _update(*a, **k):
        calls["update"] += 1
        return {"id": 99}

    def _patch(*a, **k):
        calls["patch"] += 1
        return {}

    monkeypatch.setattr(apply_mod.rest, "create_ruleset", _create)
    monkeypatch.setattr(apply_mod.rest, "update_ruleset", _update)
    monkeypatch.setattr(apply_mod.rest, "patch_allow_auto_merge", _patch)

    first = apply_mod.apply_declaration(
        _declared(), owner="upyoke", repo="yoke", token="tok",
    )
    second = apply_mod.apply_declaration(
        _declared(), owner="upyoke", repo="yoke", token="tok",
    )
    assert first["changed"] is False
    assert second["changed"] is False
    assert calls == {"create": 0, "update": 0, "patch": 0}
    assert first["remaining_drift"] == []


def test_apply_updates_when_grouping_drifted(monkeypatch):
    live_grouping = {"value": "ALLGREEN"}

    monkeypatch.setattr(
        apply_mod.rest, "list_rulesets",
        lambda *a, **k: [{"id": 99, "name": "merge-queue-main"}],
    )

    def _rules(*a, **k):
        return _live_rules(grouping=live_grouping["value"])

    monkeypatch.setattr(apply_mod.rest, "fetch_branch_rules", _rules)
    monkeypatch.setattr(
        apply_mod.rest, "fetch_repository",
        lambda *a, **k: {"allow_auto_merge": True},
    )
    monkeypatch.setattr(
        apply_mod.rest, "get_ruleset",
        lambda *a, **k: {
            "id": 99,
            "bypass_actors": [
                {
                    "actor_id": 5,
                    "actor_type": "RepositoryRole",
                    "bypass_mode": "always",
                }
            ],
        },
    )

    def _update(owner, repo, ruleset_id, body, *, token):
        live_grouping["value"] = "HEADGREEN"
        return {"id": ruleset_id}

    monkeypatch.setattr(apply_mod.rest, "update_ruleset", _update)
    monkeypatch.setattr(
        apply_mod.rest, "create_ruleset",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("create")),
    )
    monkeypatch.setattr(
        apply_mod.rest, "patch_allow_auto_merge",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("patch")),
    )

    result = apply_mod.apply_declaration(
        _declared(), owner="upyoke", repo="yoke", token="tok",
    )
    assert result["changed"] is True
    assert result["remaining_drift"] == []


def test_apply_raises_when_verify_still_drifts(monkeypatch):
    monkeypatch.setattr(
        apply_mod.rest, "list_rulesets",
        lambda *a, **k: [{"id": 99, "name": "merge-queue-main"}],
    )
    monkeypatch.setattr(
        apply_mod.rest, "fetch_branch_rules",
        lambda *a, **k: _live_rules(grouping="ALLGREEN"),
    )
    monkeypatch.setattr(
        apply_mod.rest, "fetch_repository",
        lambda *a, **k: {"allow_auto_merge": True},
    )
    monkeypatch.setattr(
        apply_mod.rest, "get_ruleset",
        lambda *a, **k: {"id": 99, "bypass_actors": []},
    )
    monkeypatch.setattr(
        apply_mod.rest, "update_ruleset",
        lambda *a, **k: {"id": 99},
    )
    with pytest.raises(RestTransportError, match="still drifts"):
        apply_mod.apply_declaration(
            _declared(), owner="upyoke", repo="yoke", token="tok",
        )
