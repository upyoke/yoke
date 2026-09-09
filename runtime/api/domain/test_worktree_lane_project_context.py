"""Lane provisioning runs as the item's project, never a default one.

Dependency setup, validation surfaces, and the browser cache are all
project-scoped. The preflight already resolves which project owns an
item's lane; forwarding its own unset ``--project`` flag into creation
instead sent a cross-repo lane's provisioning to the creator's default
project. These tests pin the resolved project travelling all the way into
provisioning, and the refusal that replaced the default.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from yoke_core.domain import worktree_create, worktree_create_db
from yoke_core.domain import worktree_preflight as wp
from yoke_core.domain.worktree_create_plan import (
    WorktreeCreationEntry,
    WorktreeCreationPlan,
)


def _git_checkout(root) -> str:
    """A real git checkout — repo-root normalization rejects a bare dir."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "--quiet", str(root)], check=True, capture_output=True
    )
    return str(root)


def _patch_preflight_steps(monkeypatch, item: dict) -> list[dict]:
    """Stub every preflight step but creation; return its captured kwargs."""
    captured: list[dict] = []

    monkeypatch.setattr(wp, "claim_work", lambda _item_id: (True, "acquired"))
    monkeypatch.setattr(
        wp, "activate_path_claims", lambda _item_id: (True, "", [])
    )
    monkeypatch.setattr(
        wp,
        "resolve_item_branch_and_lane",
        lambda _item_id: ("YOK-9101", ""),
    )
    monkeypatch.setattr(
        wp,
        "evaluate_dirty_main_for_item",
        lambda *_a, **_k: SimpleNamespace(
            blocked=False,
            kind="",
            narrative="",
            warning_note="",
            needed_paths=(),
            source_root_prefixes=(),
        ),
    )
    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        lambda **_kwargs: SimpleNamespace(
            success=True, result={"item": item}, error=None
        ),
    )

    def _fake_create(**kwargs):
        captured.append(kwargs)
        return worktree_create.CreateWorktreeResult(
            path=str(kwargs["repo_root"]) + "/.worktrees/YOK-9101",
            branch="YOK-9101",
            created=True,
        )

    monkeypatch.setattr(worktree_create, "create_worktree", _fake_create)
    return captured


def test_preflight_carries_a_cross_repo_items_project_into_creation(
    tmp_path, monkeypatch
):
    captured = _patch_preflight_steps(
        monkeypatch, {"public_ref": "PLAT-12", "project": {"slug": "platform"}}
    )
    checkout = _git_checkout(tmp_path / "platform")
    monkeypatch.setattr(
        "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
        lambda slug: checkout if slug == "platform" else None,
    )

    outcome = wp.run_preflight(item_id=9101, session_id="sess")

    assert outcome.ok is True, outcome.narrative
    assert captured[0]["project"] == "platform"
    assert captured[0]["repo_root"] == checkout


def test_preflight_carries_the_session_projects_own_item_unchanged(
    tmp_path, monkeypatch
):
    captured = _patch_preflight_steps(
        monkeypatch, {"public_ref": "YOK-9101", "project": {"slug": "yoke"}}
    )
    checkout = _git_checkout(tmp_path / "yoke")
    monkeypatch.setattr(
        "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
        lambda slug: checkout if slug == "yoke" else None,
    )

    outcome = wp.run_preflight(item_id=9101, session_id="sess")

    assert outcome.ok is True, outcome.narrative
    assert captured[0]["project"] == "yoke"


def test_preflight_refuses_a_flag_disagreeing_with_the_items_project(
    monkeypatch,
):
    _patch_preflight_steps(
        monkeypatch, {"public_ref": "PLAT-12", "project": {"slug": "platform"}}
    )

    outcome = wp.run_preflight(item_id=9101, project="yoke", session_id="sess")

    assert outcome.ok is False
    assert "disagrees" in outcome.narrative


def _provisioned_project(monkeypatch, tmp_path, **create_kwargs) -> list[str]:
    """Run creation with provisioning stubbed; return the projects it used."""
    used: list[str] = []
    entry = WorktreeCreationEntry(
        branch="YOK-9102", path=str(tmp_path / "lane"), lane_id=7
    )
    plan = WorktreeCreationPlan(worktrees=[entry], primary=entry)

    monkeypatch.setattr(
        worktree_create, "check_path_claim_gate", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        worktree_create,
        "item_worktree_authority_is_https",
        lambda: False,
    )
    monkeypatch.setattr(
        worktree_create,
        "resolve_worktree_lanes_for_item",
        lambda *_a, **_k: [("YOK-9102", entry.path, "implementation")],
    )
    monkeypatch.setattr(
        worktree_create, "preflight_worktree_plan", lambda *_a, **_k: plan
    )
    monkeypatch.setattr(worktree_create, "_count_active_worktrees", lambda *_a: (0, []))
    monkeypatch.setattr(
        worktree_create,
        "_provision_worktree",
        lambda _entry, _root, _base, project, _scripts: used.append(project),
    )
    monkeypatch.setattr(
        worktree_create, "_provision_worktree_harness_enablement", lambda *_a: None
    )
    monkeypatch.setattr(
        worktree_create, "_provision_worktree_folder_trust", lambda *_a: None
    )
    monkeypatch.setattr(
        worktree_create, "persist_item_worktrees", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        worktree_create,
        "_provision_worktree_test_environment",
        lambda _path, project=None: used.append(project),
    )

    repo = _git_checkout(tmp_path / "repo")
    result = worktree_create.create_worktree(
        9102, base_branch="main", repo_root=repo, **create_kwargs
    )
    assert result.error is None, result.error
    return used


def test_creation_resolves_the_items_project_when_the_caller_passes_none(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        worktree_create_db, "item_project_slug", lambda *_a, **_k: "platform"
    )

    assert _provisioned_project(monkeypatch, tmp_path) == ["platform", "platform"]


def test_creation_prefers_the_project_the_caller_already_resolved(
    tmp_path, monkeypatch
):
    def _must_not_read(*_a, **_k):  # pragma: no cover - carried project wins
        raise AssertionError("a carried project must not be re-read")

    monkeypatch.setattr(worktree_create_db, "item_project_slug", _must_not_read)

    used = _provisioned_project(monkeypatch, tmp_path, project="platform")
    assert used == ["platform", "platform"]


def test_creation_refuses_when_no_project_resolves(tmp_path, monkeypatch):
    monkeypatch.setattr(
        worktree_create_db, "item_project_slug", lambda *_a, **_k: ""
    )
    monkeypatch.setattr(
        worktree_create, "check_path_claim_gate", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        worktree_create, "item_worktree_authority_is_https", lambda: False
    )
    monkeypatch.setattr(
        worktree_create,
        "resolve_worktree_lanes_for_item",
        lambda *_a, **_k: [("YOK-9103", str(tmp_path / "lane"), "implementation")],
    )
    entry = WorktreeCreationEntry(branch="YOK-9103", path=str(tmp_path / "lane"))
    monkeypatch.setattr(
        worktree_create,
        "preflight_worktree_plan",
        lambda *_a, **_k: WorktreeCreationPlan(worktrees=[entry], primary=entry),
    )
    monkeypatch.setattr(worktree_create, "_count_active_worktrees", lambda *_a: (0, []))

    def _must_not_provision(*_a, **_k):  # pragma: no cover - refusal comes first
        raise AssertionError("provisioning must not run without a project")

    monkeypatch.setattr(worktree_create, "_provision_worktree", _must_not_provision)

    repo = _git_checkout(tmp_path / "repo")
    result = worktree_create.create_worktree(
        9103, base_branch="main", repo_root=repo
    )

    assert result.created is False
    assert "has no project for item 9103" in (result.error or "")
    assert "--project <slug>" in (result.error or "")


@pytest.mark.parametrize("carried", ["platform", "externalwebapp"])
def test_provisioning_project_returns_a_carried_project_unread(
    carried, monkeypatch
):
    def _must_not_read(*_a, **_k):  # pragma: no cover - carried project wins
        raise AssertionError("a carried project must not be re-read")

    monkeypatch.setattr(worktree_create_db, "item_project_slug", _must_not_read)

    assert worktree_create_db.provisioning_project(1, carried, None) == (carried, "")
