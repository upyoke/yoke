"""CLI wiring for project capability settings."""

# The shared pytest fixture intentionally shares its name with test parameters.
# ruff: noqa: F811

from __future__ import annotations

from runtime.api.domain.test_projects_capabilities_settings import (
    _settings,
    cap_db as cap_db,
)
from yoke_core.domain import projects


class TestProjectsCliWiring:
    def test_cli_create_get_set_round_trip(self, cap_db: str, capsys) -> None:
        assert projects.main(
            ["capability-set-settings", "yoke", "docker",
             '{"host":"a"}', "--new"]
        ) == 0
        capsys.readouterr()
        assert projects.main(
            ["capability-get-settings", "yoke", "docker"]
        ) == 0
        base = capsys.readouterr().out.strip()
        assert projects.main(
            ["capability-set-settings", "yoke", "docker",
             '{"host":"b"}', "--base", base]
        ) == 0
        capsys.readouterr()
        assert _settings(cap_db) == {"host": "b"}

    def test_cli_set_without_base_exits_2_teaching_flow(
        self, cap_db: str, capsys
    ) -> None:
        rc = projects.main(
            ["capability-set-settings", "yoke", "docker", "{}"]
        )
        assert rc == 2
        err = capsys.readouterr().err
        assert "--base is required" in err
        assert "capability-get-settings" in err

    def test_cli_stale_base_exits_1_with_conflict(
        self, cap_db: str, capsys
    ) -> None:
        assert projects.main(
            ["capability-set-settings", "yoke", "docker",
             '{"host":"a"}', "--new"]
        ) == 0
        rc = projects.main(
            ["capability-set-settings", "yoke", "docker",
             '{"host":"b"}', "--base", '{"host":"stale"}']
        )
        assert rc == 1
        assert "settings_conflict" in capsys.readouterr().err

    def test_cli_merge_sets_key_path(self, cap_db: str, capsys) -> None:
        rc = projects.main(
            ["capability-merge-settings", "yoke", "docker",
             "--set", "host=a", "--set", "ports.web=3000"]
        )
        assert rc == 0
        capsys.readouterr()
        final = _settings(cap_db)
        assert final["host"] == "a"
        assert final["ports"]["web"] == 3000

    def test_cli_get_missing_exits_1(self, cap_db: str) -> None:
        assert projects.main(
            ["capability-get-settings", "yoke", "absent"]
        ) == 1
