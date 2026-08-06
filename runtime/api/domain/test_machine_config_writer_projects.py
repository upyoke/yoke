"""Project-mapping writer tests (register + stamp-untagged)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import machine_config_writer as writer
from yoke_core.domain.machine_config_writer import MachineConfigWriteError
from yoke_contracts.machine_config import schema as contract


@pytest.fixture()
def home(tmp_path, monkeypatch):
    machine_home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(machine_home))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    return machine_home


def _config(home: Path) -> dict:
    return json.loads((home / "config.json").read_text())


def _seed_https(home: Path, tmp_path: Path, env: str = "stage") -> Path:
    token_file = tmp_path / f"{env}.token"
    token_file.write_text("tok\n")
    writer.set_connection(
        env, transport="https", api_url="https://api.example",
        token_file=str(token_file),
    )
    return token_file


def _rows(config: dict, checkout: str) -> list[dict]:
    return [e for e in config["projects"] if e["checkout"] == checkout]


def _row(config: dict, checkout: str, env: str | None = None) -> dict:
    rows = _rows(config, checkout)
    if env is not None:
        rows = [e for e in rows if e.get("env") == env]
    assert len(rows) == 1, rows
    return rows[0]


class TestRegisterProject:
    def test_registers_resolved_checkout(self, home, tmp_path):
        _seed_https(home, tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()

        result = writer.register_project(repo, 7)

        entry = _row(_config(home), result["checkout"])
        assert entry["project_id"] == 7
        assert entry["env"] == "stage"
        assert "board" not in entry

    def test_register_refuses_retired_board_flags(self, home, tmp_path):
        _seed_https(home, tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()

        with pytest.raises(MachineConfigWriteError, match="board is retired"):
            writer.register_project(
                repo, 7, board_scope="all",
                board_render_path=".yoke/BOARD-ALL.md",
            )

    def test_register_without_connection_env_is_refused(self, home, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()

        with pytest.raises(MachineConfigWriteError, match="connection"):
            writer.register_project(repo, 7)

    def test_register_adds_env_row_and_keeps_other_env(self, home, tmp_path):
        _seed_https(home, tmp_path, env="prod")
        _seed_https(home, tmp_path, env="stage")
        repo = tmp_path / "repo"
        repo.mkdir()
        payload = _config(home)
        payload["active_env"] = "stage"
        payload["projects"] = [
            {"checkout": str(repo.resolve()), "project_id": 9, "env": "prod"},
        ]
        (home / "config.json").write_text(json.dumps(payload), encoding="utf-8")

        result = writer.register_project(repo, 7)

        rows = sorted((e["env"], e["project_id"])
                      for e in _rows(_config(home), result["checkout"]))
        assert rows == [("prod", 9), ("stage", 7)]

    def test_register_normalizes_malformed_projects(self, home, tmp_path):
        _seed_https(home, tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()
        payload = _config(home)
        payload["projects"] = ["not", "a", "row"]
        (home / "config.json").write_text(json.dumps(payload), encoding="utf-8")

        result = writer.register_project(repo, 7)

        assert _config(home)["projects"] == [
            {"checkout": result["checkout"], "project_id": 7, "env": "stage"},
        ]

    def test_missing_directory_is_refused(self, home, tmp_path):
        _seed_https(home, tmp_path)

        with pytest.raises(MachineConfigWriteError, match="not a directory"):
            writer.register_project(tmp_path / "absent", 7)

    def test_nonpositive_project_id_is_refused(self, home, tmp_path):
        _seed_https(home, tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()

        with pytest.raises(MachineConfigWriteError, match="positive integer"):
            writer.register_project(repo, 0)


class TestStampUntaggedProjectEnvs:
    def _seed_untagged(self, home: Path, tmp_path: Path) -> None:
        _seed_https(home, tmp_path, env="prod")
        payload = _config(home)
        payload["projects"] = {
            "/checkout/one": {"project_id": 1},
            "/checkout/two": {"project_id": 2, "board": {"scope": "two"}},
        }
        (home / "config.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_stamps_untagged_entries_with_active_env(self, home, tmp_path):
        self._seed_untagged(home, tmp_path)

        result = writer.stamp_untagged_project_envs()

        assert result["env"] == "prod"
        assert {row["checkout"] for row in result["stamped"]} == {
            "/checkout/one", "/checkout/two",
        }
        config = _config(home)
        assert isinstance(config["projects"], list)
        assert _row(config, "/checkout/one")["env"] == "prod"
        assert _row(config, "/checkout/two")["env"] == "prod"
        assert "board" not in _row(config, "/checkout/two")
        assert contract.validate_payload(config) == []

    def test_leaves_already_tagged_entries_untouched(self, home, tmp_path):
        _seed_https(home, tmp_path, env="prod")
        _seed_https(home, tmp_path, env="stage")
        payload = _config(home)
        payload["projects"] = {
            "/checkout/one": {"project_id": 1},
            "/checkout/two": {"project_id": 2, "env": "stage"},
        }
        (home / "config.json").write_text(json.dumps(payload), encoding="utf-8")

        result = writer.stamp_untagged_project_envs()

        assert [row["checkout"] for row in result["stamped"]] == ["/checkout/one"]
        assert [row["checkout"] for row in result["skipped"]] == ["/checkout/two"]
        config = _config(home)
        assert _row(config, "/checkout/one")["env"] == "prod"
        assert _row(config, "/checkout/two")["env"] == "stage"

    def test_explicit_env_overrides_active(self, home, tmp_path):
        _seed_https(home, tmp_path, env="prod")
        _seed_https(home, tmp_path, env="stage")
        payload = _config(home)
        payload["projects"] = {"/checkout/one": {"project_id": 1}}
        (home / "config.json").write_text(json.dumps(payload), encoding="utf-8")

        result = writer.stamp_untagged_project_envs("stage")

        assert result["env"] == "stage"
        assert _row(_config(home), "/checkout/one")["env"] == "stage"

    def test_unknown_env_is_refused(self, home, tmp_path):
        self._seed_untagged(home, tmp_path)

        with pytest.raises(MachineConfigWriteError, match="ghost"):
            writer.stamp_untagged_project_envs("ghost")
