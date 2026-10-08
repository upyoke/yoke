"""Tests for DB-backed routing and local-only project settings."""

from __future__ import annotations

from pathlib import Path

from yoke_core.api.routing_config import (
    load_project_routing_settings,
    load_routing_config,
)
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


class TestRoutingPolicy:
    def test_project_routing_is_complete_authority(self, tmp_path: Path) -> None:
        cfg = _machine_cfg(
            tmp_path,
            "executor_default_level_claude*=LOCAL\n",
        )
        routing = load_routing_config(
            cfg,
            project_settings={
                "executor_default_level_claude*": "DARIUS",
            },
        )
        assert routing.default_level_for_executor("claude-code") == "DARIUS"

    def test_machine_routing_is_no_project_fallback(self, tmp_path: Path) -> None:
        cfg = _machine_cfg(tmp_path, "executor_default_level_codex*=ALTMAN\n")
        routing = load_routing_config(cfg)
        assert routing.default_level_for_executor("codex-desktop") == "ALTMAN"

    def test_project_routing_reader_fills_missing_defaults(self) -> None:
        class _Cursor:
            def fetchone(self) -> dict[str, str]:
                return {
                    "settings": '{"executor_default_levels":{"claude*":"ALT"}}',
                }

        class _Conn:
            def execute(self, *_args, **_kwargs) -> _Cursor:
                return _Cursor()

        settings = load_project_routing_settings(_Conn(), 2)
        routing = load_routing_config("unused", project_settings=settings)
        assert routing.default_level_for_executor("claude-code") == "ALT"
        assert routing.default_level_for_executor("codex") == "ALTMAN"
        assert "DARIUS" in routing.level_metadata

    def test_level_rules_and_metadata_survive_the_shared_double_normalization(
        self,
    ) -> None:
        # ``load_project_routing_settings`` flattens ``level_rules`` and
        # ``level_metadata`` into JSON text; every registered caller then
        # hands that flat map straight to ``load_routing_config``, which
        # normalizes it again. Both nested documents must come out the far
        # side intact rather than as a JSON string of themselves.
        class _Cursor:
            def fetchone(self) -> dict[str, str]:
                return {
                    "settings": (
                        '{"level_metadata": {"MUSKY": {"label": "MUSKY"}}, '
                        '"level_rules": [{"harness": "cursor", "level": "MUSKY"}]}'
                    ),
                }

        class _Conn:
            def execute(self, *_args, **_kwargs) -> _Cursor:
                return _Cursor()

        settings = load_project_routing_settings(_Conn(), 2)
        routing = load_routing_config("unused", project_settings=settings)

        assert routing.level_metadata == {"MUSKY": {"label": "MUSKY"}}
        assert routing.level_for_session(executor="cursor-cli") == "MUSKY"
        # A broken double-encode would have handed level_metadata back as a
        # JSON string; iterating it in ``_declared_levels`` yields one
        # phantom level per character instead of the real "MUSKY" key.
        assert list(routing.level_metadata) == ["MUSKY"]


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
