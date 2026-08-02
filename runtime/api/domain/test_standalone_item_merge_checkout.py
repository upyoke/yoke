"""Checkout authority checks for standalone item merges."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import standalone_item_merge_cli as merge_cli


def _set_yoke_checkout(
    monkeypatch: pytest.MonkeyPatch,
    checkout: Path,
) -> None:
    monkeypatch.setattr(
        "yoke_core.engines.done_transition_gates._resolve_repo_root",
        lambda: checkout,
    )


def test_missing_external_checkout_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_yoke_checkout(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
        lambda _slug: None,
    )

    with pytest.raises(RuntimeError, match="no machine-local checkout"):
        merge_cli._resolve_checkout(
            {"id": 7, "project": {"slug": "external"}}, ""
        )


def test_external_project_cannot_map_to_yoke_checkout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_yoke_checkout(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
        lambda _slug: tmp_path,
    )

    with pytest.raises(RuntimeError, match="maps to the Yoke checkout"):
        merge_cli._resolve_checkout(
            {"id": 7, "project": {"slug": "external"}}, ""
        )
