"""Pinned product checkout validation for itemless environment deploys."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from yoke_core.domain import deploy_product_source
from yoke_core.domain import deploy_pipeline


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "product"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    tracked = repo / "product.txt"
    tracked.write_text("first\n", encoding="utf-8")
    _git(repo, "add", "product.txt")
    _git(repo, "commit", "-m", "first")
    first = _git(repo, "rev-parse", "HEAD")
    tracked.write_text("second\n", encoding="utf-8")
    _git(repo, "commit", "-am", "second")
    return repo, first, _git(repo, "rev-parse", "HEAD")


def test_clean_linked_worktree_accepts_short_head_pin(tmp_path: Path) -> None:
    repo, _first, head = _repository(tmp_path)
    linked = tmp_path / "linked-product"
    _git(repo, "worktree", "add", "--detach", str(linked), head)

    source = deploy_product_source.validate_product_source(linked, head[:12])

    assert source.repo_path == str(linked.resolve())
    assert source.commit == head
    assert source.image_tag == head[:12]


def test_eleven_character_pin_canonicalizes_to_twelve(tmp_path: Path) -> None:
    repo, _first, head = _repository(tmp_path)

    source = deploy_product_source.validate_product_source(repo, head[:11])

    assert source.commit == head
    assert source.image_tag == head[:12]


def test_product_source_without_explicit_pin_derives_head(tmp_path: Path) -> None:
    repo, _first, head = _repository(tmp_path)

    source = deploy_product_source.validate_product_source(repo)

    assert source.commit == head
    assert source.image_tag == head[:12]


def test_product_source_rejects_dirty_checkout(tmp_path: Path) -> None:
    repo, _first, head = _repository(tmp_path)
    (repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(
        deploy_product_source.DeployProductSourceError, match="must be clean",
    ):
        deploy_product_source.validate_product_source(repo, head)


def test_product_source_requires_pin_to_match_head(tmp_path: Path) -> None:
    repo, first, _head = _repository(tmp_path)

    with pytest.raises(
        deploy_product_source.DeployProductSourceError,
        match="product checkout HEAD",
    ):
        deploy_product_source.validate_product_source(repo, first)


def test_product_source_is_itemless_only(tmp_path: Path) -> None:
    repo, _first, head = _repository(tmp_path)

    with pytest.raises(
        deploy_product_source.DeployProductSourceError, match="only valid for itemless",
    ):
        deploy_product_source.validate_itemless_product_source(
            str(repo), head, ["42"],
        )


def test_pipeline_rejects_product_source_on_item_bound_run(monkeypatch) -> None:
    def fake_yoke_db(*args, sd=None):
        if args[:2] == ("runs", "get"):
            return "run-1|platform|flow|prod||created|"
        if args[:2] == ("runs", "items"):
            return "run-1|42"
        return ""

    monkeypatch.setattr(deploy_pipeline, "_yoke_db", fake_yoke_db)

    rc = deploy_pipeline.run_pipeline(
        "run-1", product_repo_path="/product", image_tag="abc123",
    )

    assert rc == deploy_pipeline.EXIT_USAGE
