"""Tests for DB-backed routing and local-only project settings."""

from __future__ import annotations

from pathlib import Path

from yoke_core.api.routing_config import (
    ProcessOfferPolicy,
    load_process_offer_policy,
    load_project_routing_settings,
    load_routing_config,
)
from yoke_core.domain.project_settings import (
    get_project_int,
    get_project_str,
    offer_project_config_dir,
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
            "executor_default_lane_claude*=LOCAL\n"
            "lane_paths_local=feed\n",
        )
        routing = load_routing_config(
            cfg,
            project_settings={
                "executor_default_lane_claude*": "DARIUS",
                "lane_paths_darius": "shepherd,conduct",
            },
        )
        assert routing.default_lane_for_executor("claude-code") == "DARIUS"
        assert routing.lane_allowed_paths == {
            "DARIUS": ["shepherd", "conduct"],
        }

    def test_machine_routing_is_no_project_fallback(self, tmp_path: Path) -> None:
        cfg = _machine_cfg(tmp_path, "executor_default_lane_codex*=ALTMAN\n")
        routing = load_routing_config(cfg)
        assert routing.default_lane_for_executor("codex-desktop") == "ALTMAN"

    def test_project_routing_reader_fills_missing_defaults(self) -> None:
        class _Cursor:
            def fetchone(self) -> dict[str, str]:
                return {
                    "settings": '{"executor_default_lanes":{"claude*":"ALT"}}',
                }

        class _Conn:
            def execute(self, *_args, **_kwargs) -> _Cursor:
                return _Cursor()

        settings = load_project_routing_settings(_Conn(), 2)
        routing = load_routing_config("unused", project_settings=settings)
        assert routing.default_lane_for_executor("claude-code") == "ALT"
        assert routing.default_lane_for_executor("codex") == "ALTMAN"
        assert "DARIUS" in routing.lane_allowed_paths


class TestProcessPolicy:
    def test_project_process_policy_ignores_machine(self, tmp_path: Path) -> None:
        cfg = _machine_cfg(tmp_path, "do_process_offer_strategize=true\n")
        policy = load_process_offer_policy(
            cfg,
            project_settings={"do_process_offer_default": "false"},
            shared_project_source="project 2 capability session-routing",
        )
        enabled, key, source = policy.decision_for("STRATEGIZE")
        assert enabled is False
        assert key == "do_process_offer_strategize"
        assert source == "project 2 capability session-routing"

    def test_machine_policy_is_no_project_fallback(self, tmp_path: Path) -> None:
        cfg = _machine_cfg(tmp_path, "do_process_offer_feed=true\n")
        policy = load_process_offer_policy(cfg)
        assert policy.is_enabled("FEED") is True
        assert policy.decision_for("FEED")[2] == "machine config"

    def test_skip_memory_keeps_project_source(self) -> None:
        from yoke_core.domain.chain_skip_memory_filter import (
            merge_skip_memory_with_policy,
        )

        policy = ProcessOfferPolicy(
            shared_project_per_process={"strategize": True},
            shared_project_source="project capability session-routing",
        )
        merged = merge_skip_memory_with_policy(
            policy, [{"process_key": "STRATEGIZE"}],
        )
        assert merged is not None
        assert merged.is_enabled("STRATEGIZE") is False
        assert (
            merged.shared_project_source
            == "project capability session-routing"
        )


class TestLocalOnlySettings:
    def test_db_owned_keys_ignore_machine_config_without_project_identity(
        self, tmp_path: Path,
    ) -> None:
        cfg = _machine_cfg(tmp_path, "base_branch=develop\n")
        repo = _project_dir(tmp_path)
        assert get_project_str(
            repo, "base_branch", config_path=cfg,
        ) == "main"
        assert get_project_int(repo, "wip_cap", config_path=cfg) == 5

    def test_worktrees_dir_remains_machine_local(self, tmp_path: Path) -> None:
        cfg = _machine_cfg(tmp_path, "worktrees_dir=.wt\n")
        repo = _project_dir(tmp_path)
        assert get_project_str(
            repo, "worktrees_dir", config_path=cfg,
        ) == ".wt"


class TestOfferDirResolution:
    def _machine(self, tmp_path: Path, mapping: dict) -> Path:
        import json

        cfg = tmp_path / "machine.json"
        cfg.write_text(json.dumps({"projects": mapping}), encoding="utf-8")
        return cfg

    def test_mapped_workspace_wins(self, tmp_path: Path) -> None:
        repo = tmp_path / "checkout"
        (repo / ".git").mkdir(parents=True)
        cfg = self._machine(tmp_path, {str(repo): {"project_id": 2}})
        resolved = offer_project_config_dir(
            str(repo), [1, 2], machine_config_path=cfg,
        )
        assert resolved == repo

    def test_single_scope_falls_back_to_mapped_checkout(
        self, tmp_path: Path,
    ) -> None:
        other = tmp_path / "other-checkout"
        other.mkdir()
        workspace = tmp_path / "unmapped"
        workspace.mkdir()
        cfg = self._machine(tmp_path, {str(other): {"project_id": 3}})
        resolved = offer_project_config_dir(
            str(workspace), [3], machine_config_path=cfg,
        )
        assert resolved == other

    def test_multi_scope_unmapped_workspace_is_none(
        self, tmp_path: Path,
    ) -> None:
        workspace = tmp_path / "unmapped"
        workspace.mkdir()
        cfg = self._machine(tmp_path, {})
        assert offer_project_config_dir(
            str(workspace), [1, 2], machine_config_path=cfg,
        ) is None
