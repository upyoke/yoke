"""Item-project repo-root resolution for the worktree preflight.

The lane belongs in the checkout of the ITEM's project. These unit tests
pin the resolution order: explicit override, flag/item agreement, machine
mapping, refusal on an unmapped item project, and the cwd fallback that
survives only when the item's project is unknown (degraded detail read).
"""

from __future__ import annotations

import pytest

from yoke_core.domain import worktree_preflight_repo_resolution as res


def _item(slug: str) -> dict:
    return {"project": {"slug": slug}}


def test_explicit_override_wins_untouched(monkeypatch: pytest.MonkeyPatch):
    def refuse(*_a, **_k):  # pragma: no cover - must not be called
        raise AssertionError("override must not consult the mapping")

    monkeypatch.setattr(
        "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
        refuse,
    )
    root, error = res.resolve_preflight_repo_root(
        item=_item("platform"),
        project_flag=None,
        repo_root_override="/tmp/explicit",
    )
    assert (root, error) == ("/tmp/explicit", "")


def test_mapped_item_project_uses_the_mapping(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
        lambda slug: "/checkouts/platform" if slug == "platform" else None,
    )
    root, error = res.resolve_preflight_repo_root(
        item=_item("platform"), project_flag=None, repo_root_override=None,
    )
    assert (root, error) == ("/checkouts/platform", "")


def test_unmapped_item_project_refuses_with_register_recipe(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
        lambda _slug: None,
    )
    root, error = res.resolve_preflight_repo_root(
        item=_item("platform"), project_flag=None, repo_root_override=None,
    )
    assert root == ""
    assert "yoke project register" in error
    assert "wrong repository" in error


def test_flag_disagreeing_with_item_project_refuses(
    monkeypatch: pytest.MonkeyPatch,
):
    def refuse(*_a, **_k):  # pragma: no cover - mismatch refuses first
        raise AssertionError("mismatch must refuse before mapping lookup")

    monkeypatch.setattr(
        "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
        refuse,
    )
    root, error = res.resolve_preflight_repo_root(
        item=_item("platform"), project_flag="yoke", repo_root_override=None,
    )
    assert root == ""
    assert "disagrees" in error


def test_agreeing_flag_resolves_like_the_item(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
        lambda slug: "/checkouts/platform" if slug == "platform" else None,
    )
    root, error = res.resolve_preflight_repo_root(
        item=_item("platform"),
        project_flag="platform",
        repo_root_override=None,
    )
    assert (root, error) == ("/checkouts/platform", "")


def test_unknown_item_project_falls_back_to_cwd(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "yoke_core.domain.worktree_paths._resolve_repo_root_from_cwd",
        lambda: "/checkouts/session-repo",
    )
    root, error = res.resolve_preflight_repo_root(
        item={}, project_flag=None, repo_root_override=None,
    )
    assert (root, error) == ("/checkouts/session-repo", "")


def test_unmapped_flag_without_item_project_falls_back_to_cwd(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
        lambda _slug: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.worktree_paths._resolve_repo_root_from_cwd",
        lambda: "/checkouts/session-repo",
    )
    root, error = res.resolve_preflight_repo_root(
        item={}, project_flag="somewhere", repo_root_override=None,
    )
    assert (root, error) == ("/checkouts/session-repo", "")


def test_no_resolution_anywhere_reports_input_error(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "yoke_core.domain.worktree_paths._resolve_repo_root_from_cwd",
        lambda: "",
    )
    root, error = res.resolve_preflight_repo_root(
        item={}, project_flag=None, repo_root_override=None,
    )
    assert root == ""
    assert "Could not resolve repo root" in error
