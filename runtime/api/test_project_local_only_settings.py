"""Project settings that stay machine-local, and DB-owned ones that do not."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.project_contract.project_keys import RECOGNIZED_PROJECT_KEYS
from yoke_core.domain.project_settings import (
    get_project_int,
    get_project_str,
)


def _machine_cfg(tmp_path: Path, lines: str) -> Path:
    cfg = tmp_path / "machine-config"
    cfg.write_text(lines, encoding="utf-8")
    return cfg


def _project_dir(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".yoke").mkdir(parents=True, exist_ok=True)
    return repo


class TestLocalOnlySettings:
    def test_db_owned_keys_ignore_machine_config_without_project_identity(
        self,
        tmp_path: Path,
    ) -> None:
        cfg = _machine_cfg(tmp_path, "base_branch=develop\n")
        repo = _project_dir(tmp_path)
        assert (
            get_project_str(
                repo,
                "base_branch",
                config_path=cfg,
            )
            == RECOGNIZED_PROJECT_KEYS["base_branch"][0]
        )
        assert get_project_int(repo, "wip_cap", config_path=cfg) == int(
            RECOGNIZED_PROJECT_KEYS["wip_cap"][0]
        )

    def test_worktrees_dir_remains_machine_local(self, tmp_path: Path) -> None:
        cfg = _machine_cfg(tmp_path, "worktrees_dir=.wt\n")
        repo = _project_dir(tmp_path)
        assert (
            get_project_str(
                repo,
                "worktrees_dir",
                config_path=cfg,
            )
            == ".wt"
        )
