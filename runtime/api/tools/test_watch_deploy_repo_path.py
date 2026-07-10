"""Pinned-product build-context propagation for the deploy watcher."""

from __future__ import annotations

import pytest

from yoke_core.domain.deploy_product_source import DeployProductSource
from yoke_core.tools import watch_deploy
from yoke_core.tools import watch_deploy_product_source


def _run(
    monkeypatch: pytest.MonkeyPatch, tmp_path, deploy_args: list[str],
    *, explicit: str = "", expected_rc: int = 0,
):
    seen = {}
    monkeypatch.setattr(
        watch_deploy._watch_runner,
        "run_watcher",
        lambda **kwargs: seen.update(kwargs) or 0,
    )
    monkeypatch.setattr(
        watch_deploy._source_pythonpath,
        "import_origin_refusal",
        lambda root, **kwargs: None,
    )
    product_root = tmp_path / "product"
    product_root.mkdir()
    monkeypatch.setattr(
        watch_deploy_product_source,
        "validate_product_source",
        lambda root, tag: DeployProductSource(str(root.resolve()), "a" * 40),
    )
    if explicit == "matching":
        deploy_args.extend(["--product-repo-path", str(product_root.resolve())])
    elif explicit:
        deploy_args.extend(["--product-repo-path", explicit])
    rc = watch_deploy.main([
        "--product-src", str(product_root),
        "--raw-capture", str(tmp_path / "raw.log"),
        "--progress-capture", str(tmp_path / "progress.log"),
        "--", *deploy_args,
    ])
    assert rc == expected_rc
    return seen.get("argv"), product_root.resolve()


def test_product_src_becomes_deploy_repo_path(monkeypatch, tmp_path) -> None:
    argv, product_root = _run(
        monkeypatch, tmp_path, ["run-1", "--image-tag", "abc123"],
    )

    assert argv[-2:] == ["--product-repo-path", str(product_root)]


def test_explicit_repo_path_is_not_duplicated(monkeypatch, tmp_path) -> None:
    argv, product_root = _run(
        monkeypatch, tmp_path, ["run-1", "--image-tag=abc123"],
        explicit="matching",
    )

    assert argv.count("--product-repo-path") == 1
    assert argv[-1] == str(product_root)


def test_conflicting_product_repo_path_is_rejected(monkeypatch, tmp_path) -> None:
    argv, _ = _run(
        monkeypatch, tmp_path, ["run-1", "--image-tag", "abc123"],
        explicit="/different", expected_rc=3,
    )

    assert argv is None


def test_streaming_pair_preserves_product_source(monkeypatch, tmp_path, capsys) -> None:
    product_root = tmp_path / "product"
    product_root.mkdir()
    monkeypatch.setattr(
        watch_deploy._source_pythonpath, "import_origin_refusal",
        lambda root, **kwargs: None,
    )
    monkeypatch.setattr(
        watch_deploy_product_source, "validate_product_source",
        lambda root, tag: DeployProductSource(str(root.resolve()), "a" * 40),
    )

    rc = watch_deploy.main([
        "--print-streaming-pair", "--product-src", str(product_root),
        "--", "run-1", "--image-tag", "abc123",
    ])

    assert rc == 0
    background = capsys.readouterr().out
    assert f"--product-src {product_root.resolve()}" in background
    assert f"--product-repo-path {product_root.resolve()}" in background
