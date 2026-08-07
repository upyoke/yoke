"""Install/refresh refuses checkout↔project_id disagreements with machine config."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import machine_config, machine_config_writer, project_install
from yoke_core.domain.project_install import ProjectInstallError
from yoke_core.domain.project_install_test_helpers import make_bundle


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


def _tree_bytes(root: Path) -> dict[str, bytes | str]:
    snapshot: dict[str, bytes | str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        snapshot[rel] = (
            f"symlink:{path.readlink()}" if path.is_symlink()
            else path.read_bytes() if path.is_file()
            else "directory"
        )
    return snapshot


def _seed_envs(cfg: Path, tmp_path: Path) -> None:
    prod_dsn = tmp_path / "prod.dsn"
    stage_dsn = tmp_path / "stage.dsn"
    prod_dsn.write_text("postgresql://localhost/prod\n", encoding="utf-8")
    stage_dsn.write_text("postgresql://localhost/stage\n", encoding="utf-8")
    machine_config_writer.set_connection(
        "prod", transport="local-postgres", dsn_file=str(prod_dsn), path=cfg,
    )
    machine_config_writer.set_connection(
        "stage", transport="local-postgres", dsn_file=str(stage_dsn), path=cfg,
    )
    machine_config_writer.set_active_env("prod", path=cfg)


def test_explicit_project_id_mismatch_refuses_before_bundle_or_writes(
    repo, tmp_path, monkeypatch,
) -> None:
    cfg = tmp_path / "machine-home" / "config.json"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    _seed_envs(cfg, tmp_path)
    machine_config_writer.register_project(repo, 3, path=cfg)

    def _bundle_unreachable(*_a, **_k):
        raise AssertionError("bundle must not resolve after mapping refusal")

    monkeypatch.setattr(project_install, "_resolve_bundle", _bundle_unreachable)
    before = _tree_bytes(repo)

    with pytest.raises(ProjectInstallError, match="mapped to project_id 3"):
        project_install.install(repo, project_id=9, config_path=cfg)

    assert _tree_bytes(repo) == before
    assert machine_config.project_id(repo, cfg) == 3


def test_other_env_only_mapping_refuses_explicit_project_id(
    repo, tmp_path, monkeypatch,
) -> None:
    cfg = tmp_path / "machine-home" / "config.json"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    _seed_envs(cfg, tmp_path)
    machine_config_writer.register_project(repo, 3, path=cfg)  # prod
    monkeypatch.setenv("YOKE_ENV", "stage")

    def _bundle_unreachable(*_a, **_k):
        raise AssertionError("bundle must not resolve after mapping refusal")

    monkeypatch.setattr(project_install, "_resolve_bundle", _bundle_unreachable)
    before = _tree_bytes(repo)

    with pytest.raises(ProjectInstallError, match="mapped only for another env"):
        project_install.install(repo, project_id=3, config_path=cfg)

    assert _tree_bytes(repo) == before
    assert machine_config.project_id(repo, cfg) is None


def test_matching_explicit_project_id_still_installs(
    repo, tmp_path, monkeypatch,
) -> None:
    cfg = tmp_path / "machine-home" / "config.json"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    _seed_envs(cfg, tmp_path)
    machine_config_writer.register_project(repo, 7, path=cfg)
    monkeypatch.setattr(
        project_install, "_resolve_bundle",
        lambda *_a, **_k: (make_bundle(), "test"),
    )

    report = project_install.install(repo, project_id=7, config_path=cfg)

    assert report["machine_config_newly_registered"] is False
    assert machine_config.project_id(repo, cfg) == 7
