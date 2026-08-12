"""Checkout authority checks for standalone item merges.

The merge lands in the checkout the ITEM's project maps to. Resolving it
from the session's own repository instead broke every cross-project
close-out: from a yoke workspace the merge reached for the wrong tree, and
from the item's own workspace the mapping matched that tree and was
mistaken for a misconfiguration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import standalone_item_merge_cli as merge_cli


def _refuse_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mapped project must never consult the session's own repo."""

    def refuse() -> str:  # pragma: no cover - called only on regression
        raise AssertionError("mapped project must not fall back to cwd")

    monkeypatch.setattr(
        "yoke_core.domain.worktree_paths._resolve_repo_root_from_cwd", refuse,
    )


def _map_checkouts(
    monkeypatch: pytest.MonkeyPatch, mapping: dict[str, Path]
) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
        lambda slug: mapping.get(slug),
    )
    monkeypatch.setattr(
        "yoke_core.engines.done_transition_gates._resolve_default_branch",
        lambda _slug: "main",
    )


def test_external_project_uses_its_own_checkout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    external = tmp_path / "external"
    external.mkdir()
    _refuse_cwd(monkeypatch)
    _map_checkouts(monkeypatch, {"external": external, "yoke": tmp_path / "yoke"})

    assert merge_cli._resolve_checkout(
        {"id": 7, "project": {"slug": "external"}}, "",
    ) == (external, "main")


def test_external_project_resolves_from_its_own_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The item's mapping is authority even when it IS the session's repo."""
    external = tmp_path / "external"
    external.mkdir()
    monkeypatch.chdir(external)
    _map_checkouts(monkeypatch, {"external": external})

    assert merge_cli._resolve_checkout(
        {"id": 7, "project": {"slug": "external"}}, "",
    ) == (external, "main")


def test_self_project_uses_its_mapping_not_the_session_repo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    yoke = tmp_path / "yoke"
    yoke.mkdir()
    _refuse_cwd(monkeypatch)
    _map_checkouts(monkeypatch, {"yoke": yoke, "external": tmp_path / "external"})

    assert merge_cli._resolve_checkout(
        {"id": 7, "project": {"slug": "yoke"}}, "",
    ) == (yoke, "main")


def test_missing_checkout_mapping_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _map_checkouts(monkeypatch, {})

    with pytest.raises(RuntimeError, match="no machine-local checkout mapping"):
        merge_cli._resolve_checkout(
            {"id": 7, "project": {"slug": "external"}}, "",
        )


def test_target_override_wins_over_the_project_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    external = tmp_path / "external"
    external.mkdir()
    _map_checkouts(monkeypatch, {"external": external})

    assert merge_cli._resolve_checkout(
        {"id": 7, "project": {"slug": "external"}}, "release",
    ) == (external, "release")
