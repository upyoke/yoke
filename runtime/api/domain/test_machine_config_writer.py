"""Tests for the machine-config writers (env use / connection set /
auth set / project register)."""

from __future__ import annotations

import io
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


class TestSetConnection:
    def test_create_writes_valid_config_and_activates_first_env(
        self, home, tmp_path,
    ):
        _seed_https(home, tmp_path)

        payload = _config(home)
        assert payload["active_env"] == "stage"
        entry = payload["connections"]["stage"]
        assert entry["transport"] == "https"
        assert entry["api_url"] == "https://api.example"
        assert entry["credential_source"]["kind"] == "token_file"
        mode = (home / "config.json").stat().st_mode & 0o777
        assert mode == 0o600

    def test_second_env_does_not_steal_active(self, home, tmp_path):
        _seed_https(home, tmp_path, env="prod")
        _seed_https(home, tmp_path, env="stage")

        assert _config(home)["active_env"] == "prod"

    def test_update_merges_only_given_fields(self, home, tmp_path):
        _seed_https(home, tmp_path)

        writer.set_connection("stage", api_url="https://api2.example")

        entry = _config(home)["connections"]["stage"]
        assert entry["api_url"] == "https://api2.example"
        assert entry["credential_source"]["kind"] == "token_file"

    def test_new_env_requires_transport(self, home):
        with pytest.raises(MachineConfigWriteError, match="--transport"):
            writer.set_connection("stage", api_url="https://api.example")

    def test_invalid_result_is_refused_and_not_written(self, home):
        with pytest.raises(MachineConfigWriteError, match="api_url_required"):
            writer.set_connection("stage", transport="https")

        assert not (home / "config.json").exists()
        assert not (home / "config.json.tmp").exists()

    def test_credential_flags_are_mutually_exclusive(self, home):
        with pytest.raises(MachineConfigWriteError, match="mutually exclusive"):
            writer.set_connection(
                "stage", transport="https", api_url="https://api.example",
                token_file="/a", dsn_file="/b",
            )

    def test_local_postgres_defaults_to_explicit_non_prod(
        self, home, tmp_path,
    ):
        dsn = tmp_path / "prod-named.dsn"
        dsn.write_text("postgresql://admin@localhost/yoke_prod\n")

        writer.set_connection(
            "prod", transport="local-postgres", dsn_file=str(dsn),
        )

        entry = _config(home)["connections"]["prod"]
        assert entry[contract.PROD_FLAG_KEY] is False

    def test_prod_flag_can_be_set_and_cleared(self, home, tmp_path):
        _seed_https(home, tmp_path)

        writer.set_connection("stage", prod=True)
        writer.set_connection("stage", prod=False)

        entry = _config(home)["connections"]["stage"]
        assert entry[contract.PROD_FLAG_KEY] is False
        assert entry["api_url"] == "https://api.example"


class TestSetActiveEnv:
    def test_switches_between_configured_envs(self, home, tmp_path):
        _seed_https(home, tmp_path, env="prod")
        _seed_https(home, tmp_path, env="stage")

        result = writer.set_active_env("stage")

        assert result["active_env"] == "stage"
        assert _config(home)["active_env"] == "stage"

    def test_unknown_env_is_refused_naming_configured(self, home, tmp_path):
        _seed_https(home, tmp_path, env="prod")

        with pytest.raises(MachineConfigWriteError, match="prod"):
            writer.set_active_env("ghost")


class TestSetCredential:
    def test_token_stdin_stores_secret_owner_only(
        self, home, tmp_path, monkeypatch,
    ):
        _seed_https(home, tmp_path)
        monkeypatch.setattr("sys.stdin", io.StringIO("s3cret-token\n"))

        result = writer.set_credential("stage", token_stdin=True)

        token_path = Path(result["credential_source"]["path"])
        assert token_path == home / "secrets" / "stage.token"
        assert token_path.read_text() == "s3cret-token\n"
        assert token_path.stat().st_mode & 0o777 == 0o600
        entry = _config(home)["connections"]["stage"]
        assert entry["credential_source"]["path"] == str(token_path)

    def test_empty_stdin_is_refused(self, home, tmp_path, monkeypatch):
        _seed_https(home, tmp_path)
        monkeypatch.setattr("sys.stdin", io.StringIO("   \n"))

        with pytest.raises(MachineConfigWriteError, match="stdin"):
            writer.set_credential("stage", token_stdin=True)

    def test_requires_exactly_one_source(self, home, tmp_path):
        _seed_https(home, tmp_path)

        with pytest.raises(MachineConfigWriteError, match="exactly one"):
            writer.set_credential("stage")
        with pytest.raises(MachineConfigWriteError, match="mutually exclusive"):
            writer.set_credential("stage", token_file="/a", token_stdin=True)

    def test_missing_env_is_refused(self, home, tmp_path):
        _seed_https(home, tmp_path)

        with pytest.raises(MachineConfigWriteError, match="connection set"):
            writer.set_credential("ghost", token_file="/a")

    def test_dsn_rotation_on_local_postgres(self, home, tmp_path):
        dsn = tmp_path / "prod.dsn"
        dsn.write_text("postgresql://x\n")
        writer.set_connection("prod", transport="local-postgres",
                              dsn_file=str(dsn))

        new_dsn = tmp_path / "prod2.dsn"
        new_dsn.write_text("postgresql://y\n")
        writer.set_credential("prod", dsn_file=str(new_dsn))

        entry = _config(home)["connections"]["prod"]
        assert entry["credential_source"] == {
            "kind": "dsn_file", "path": str(home / "secrets" / "prod.dsn"),
        }
        assert (home / "secrets" / "prod.dsn").read_text() == "postgresql://y\n"


class TestRegisterProject:
    def test_registers_resolved_checkout(self, home, tmp_path):
        _seed_https(home, tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()

        result = writer.register_project(
            repo, 7, board_scope="all",
            board_render_path=".yoke/BOARD-ALL.md",
        )

        checkout = result["checkout"]
        entry = _config(home)["projects"][checkout]
        assert entry["project_id"] == 7
        assert entry["board"] == {
            "scope": "all", "render_path": ".yoke/BOARD-ALL.md",
        }

    def test_register_repairs_project_map_entries(self, home, tmp_path):
        _seed_https(home, tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()
        old_checkout = tmp_path / "old"
        old_checkout.mkdir()
        other_checkout = tmp_path / "other"
        other_checkout.mkdir()
        payload = _config(home)
        payload["projects"] = {
            "": {"project_id": 99},
            str(old_checkout): {"project_id": 7, "extra": "removed"},
            str(other_checkout): {
                "project_id": "8",
                "extra": "removed",
                "board": {
                    "scope": "all",
                    "render_path": "",
                    "extra": "removed",
                },
            },
            str(tmp_path / "bad-entry"): "not an object",
            str(tmp_path / "bad-id"): {"project_id": "nope"},
        }
        (home / "config.json").write_text(json.dumps(payload), encoding="utf-8")

        result = writer.register_project(repo, 7)

        projects = _config(home)["projects"]
        assert set(projects) == {str(other_checkout), result["checkout"]}
        assert projects[str(other_checkout)] == {
            "project_id": 8, "board": {"scope": "all"},
        }
        assert projects[result["checkout"]] == {"project_id": 7}

    def test_register_repairs_malformed_project_map(self, home, tmp_path):
        _seed_https(home, tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()
        payload = _config(home)
        payload["projects"] = ["not", "a", "map"]
        (home / "config.json").write_text(json.dumps(payload), encoding="utf-8")

        result = writer.register_project(repo, 7)

        assert _config(home)["projects"] == {
            result["checkout"]: {"project_id": 7},
        }

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
