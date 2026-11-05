"""Concrete Git-history evidence at review, local merge, and preflight."""

import json
from types import SimpleNamespace

import pytest

from runtime.api.domain.migration_merge_preflight_test_support import _lane, _write
from runtime.api.fixtures.migration_model_test import (
    governed_postgres_test_seed,
    TEST_MIGRATION_MODULES_DIR,
)
from yoke_core.domain.migration_merge_preflight import (
    lane_only_migration_entries,
    evaluate_migration_merge,
)
from yoke_core.domain.new_migrations_db_claim_gate import (
    missing_claim_errors,
    check_item,
)
from yoke_core.domain import merge_review_readiness as review

REF = "ITEM-1"


def test_lane_only_names_use_target_history_and_include_uncommitted_entries(tmp_path):
    repo = _lane(tmp_path, "0014_new")
    _write(repo, "0015_next")
    assert lane_only_migration_entries(repo, TEST_MIGRATION_MODULES_DIR, "main") == (
        "0014_new",
        "0015_next",
    )


@pytest.mark.parametrize(
    "profile", [None, {"state": "none"}, {"state": "none", "reviewed_negative": True}]
)
def test_missing_claim_names_every_file_and_recovery(tmp_path, profile):
    repo = _lane(tmp_path, "0014_new")
    _write(repo, "0015_next")
    errors = missing_claim_errors(
        profile=profile,
        settings=governed_postgres_test_seed(),
        worktree_path=repo,
        integration_target="main",
        public_ref=REF,
    )
    text = "\n".join(errors)
    assert "lane adds migration entries without a declared DB claim" in text
    for name in ("0014_new", "0015_next"):
        assert f"{TEST_MIGRATION_MODULES_DIR}/{name}.py" in text
    assert f"yoke db-claim amend {REF}" in text


def test_all_models_are_inspected(tmp_path):
    repo = _lane(tmp_path, "0014_new")
    settings = governed_postgres_test_seed()
    settings["models"]["secondary"] = json.loads(
        json.dumps(settings["models"]["primary"])
    )
    settings["models"]["primary"]["runner"]["config"]["modules_dir"] = "empty"
    (repo / "empty").mkdir()
    errors = missing_claim_errors(
        profile=None,
        settings=settings,
        worktree_path=repo,
        integration_target="main",
        public_ref=REF,
    )
    assert "0014_new.py" in errors[0]


def test_no_new_entries_no_capability_and_declared_claim_pass(tmp_path):
    repo = _lane(tmp_path, "0014_new")
    for settings, profile in [
        (None, None),
        (governed_postgres_test_seed(), {"state": "declared"}),
    ]:
        assert not missing_claim_errors(
            profile=profile,
            settings=settings,
            worktree_path=repo,
            integration_target="main",
            public_ref=REF,
        )
    (repo / TEST_MIGRATION_MODULES_DIR / "0014_new.py").unlink()
    assert not missing_claim_errors(
        profile=None,
        settings=governed_postgres_test_seed(),
        worktree_path=repo,
        integration_target="main",
        public_ref=REF,
    )


def test_preflight_checks_none_claim(tmp_path):
    repo = _lane(tmp_path, "0014_new")
    decision = evaluate_migration_merge(
        rows=[{"id": REF, "db_mutation_profile": {"state": "none"}}],
        public_ref=REF,
        capability_settings_json=json.dumps(governed_postgres_test_seed()),
        worktree_path=repo,
        integration_target="main",
    )
    assert decision.applicable and not decision.passed
    assert "0014_new.py" in decision.errors[0]
    assert f"yoke db-claim amend {REF}" in decision.errors[0]


@pytest.mark.parametrize("claim", ["none", "declared"])
def test_review_check_runs_locally_without_prose_dispatch(tmp_path, monkeypatch, claim):
    repo = _lane(tmp_path, "0014_new")
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs["function_id"])
        if kwargs["function_id"] == "items.get.run":
            return SimpleNamespace(
                success=True,
                result={"fields": {"db_mutation_profile": {"state": claim}}},
            )
        assert kwargs["payload"]["project"] == "test"
        return SimpleNamespace(
            success=True,
            result={"settings_json": json.dumps(governed_postgres_test_seed())},
        )

    monkeypatch.setattr(review, "call_dispatcher", dispatch)
    refusal = review.review_entry_refusal(
        REF,
        review.ReviewReadiness(
            review_stage="review", review_gates=("new_migrations_need_db_claim",)
        ),
        item={"project": {"slug": "test"}, "worktrees": [{"path": str(repo)}]},
    )
    if claim == "declared":
        assert refusal == ""
    else:
        assert "0014_new.py" in refusal
        assert f"yoke db-claim amend {REF}" in refusal
    assert calls == ["projects.capability_settings.get", "items.get.run"]


def test_authoritative_check_skips_unmapped_host(monkeypatch):
    from yoke_core.domain import db_mutation_gate_implementing as implementing

    monkeypatch.setattr(implementing, "_item_lane_path", lambda *_: None)
    assert check_item(1, db_path="unused", conn=object()) is None


def test_authoritative_review_dispatch_uses_files_not_spec(
    test_db, tmp_path, monkeypatch
):
    from runtime.api.fixtures.backlog import insert_item
    from yoke_core.domain import db_mutation_gate_implementing as implementing
    from yoke_core.domain import db_mutation_gate_loaders as loaders
    from yoke_core.domain.backlog_authoritative_status_gate import (
        _evaluate_definition_gate,
    )
    from yoke_core.domain.project_identity import render_item_ref

    item_id = 948
    insert_item(
        test_db,
        id=item_id,
        workflow_id="dash",
        status="implementing",
        spec="ALTER TABLE widgets; add no column or table; do not backfill old data.",
    )
    repo = _lane(tmp_path, "0014_new")
    monkeypatch.setattr(implementing, "_item_lane_path", lambda *_: repo)
    monkeypatch.setattr(
        loaders, "_load_capability_settings", lambda *_: governed_postgres_test_seed()
    )

    def evaluate():
        return _evaluate_definition_gate(
            gate_id="new_migrations_need_db_claim",
            mode=None,
            item_id=item_id,
            target_status="reviewing-implementation",
            db_path="unused",
            conn=test_db,
        )

    refusal = evaluate()
    assert refusal["error_code"] == "GATE_NEW_MIGRATIONS_NEED_DB_CLAIM"
    assert "0014_new.py" in refusal["error"]
    assert (
        f"yoke db-claim amend {render_item_ref(test_db, item_id)}" in refusal["error"]
    )
    (repo / TEST_MIGRATION_MODULES_DIR / "0014_new.py").unlink()
    assert evaluate() is None
