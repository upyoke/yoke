"""Tests for the machine-config writers (env use / connection set / auth set)."""

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


class TestRemoveConnection:
    def test_removes_inactive_alias_owned_secret_and_mappings(self, home, tmp_path):
        _seed_https(home, tmp_path, env="prod")
        _seed_https(home, tmp_path, env="hosted-prod")
        repo = tmp_path / "repo"
        repo.mkdir()
        writer.set_active_env("hosted-prod")
        writer.register_project(repo, 7)
        secret = home / "secrets" / "prod.token"

        report = writer.remove_connection("prod")

        assert report["credential_removed"] is True
        assert "prod" not in _config(home)["connections"]
        assert not secret.exists()

    def test_refuses_active_or_non_owned_authority(self, home, tmp_path):
        _seed_https(home, tmp_path, env="prod")
        with pytest.raises(MachineConfigWriteError, match="active authority"):
            writer.remove_connection("prod")

        _seed_https(home, tmp_path, env="hosted-prod")
        writer.set_active_env("hosted-prod")
        payload = _config(home)
        external = tmp_path / "external.token"
        external.write_text("secret")
        payload["connections"]["prod"]["credential_source"]["path"] = str(external)
        (home / "config.json").write_text(json.dumps(payload), encoding="utf-8")
        (home / "config.json").chmod(0o600)
        with pytest.raises(MachineConfigWriteError, match="outside Yoke-owned"):
            writer.remove_connection("prod")

    def test_keeps_credential_referenced_by_canonical_connection(
        self, home, tmp_path,
    ):
        _seed_https(home, tmp_path, env="prod")
        _seed_https(home, tmp_path, env="canonical")
        writer.set_active_env("canonical")
        payload = _config(home)
        canonical_source = payload["connections"]["canonical"]["credential_source"]
        payload["connections"]["prod"]["credential_source"] = canonical_source
        (home / "config.json").write_text(json.dumps(payload), encoding="utf-8")
        (home / "config.json").chmod(0o600)

        report = writer.remove_connection("prod")

        assert report["credential_removed"] is False
        assert report["credential_retained_shared"] is True
        assert Path(canonical_source["path"]).is_file()
        assert "canonical" in _config(home)["connections"]

    def test_recovers_legacy_retiring_tombstone_before_config_write(
        self, home, tmp_path,
    ):
        _seed_https(home, tmp_path, env="prod")
        _seed_https(home, tmp_path, env="canonical")
        writer.set_active_env("canonical")
        secret = home / "secrets" / "prod.token"
        tombstone = secret.with_name(secret.name + ".retiring")
        secret.replace(tombstone)

        report = writer.remove_connection("prod")

        assert report["credential_removed"] is True
        assert not tombstone.exists()
        assert "prod" not in _config(home)["connections"]

    def test_recovers_tombstone_after_config_write(self, home, tmp_path):
        _seed_https(home, tmp_path, env="prod")
        _seed_https(home, tmp_path, env="canonical")
        writer.set_active_env("canonical")
        secret = home / "secrets" / "prod.token"
        from yoke_cli.config import writer_connection_remove as retirement

        tombstone = retirement._retirement_tombstone("prod")
        secret.replace(tombstone)
        payload = _config(home)
        payload["connections"].pop("prod")
        (home / "config.json").write_text(json.dumps(payload), encoding="utf-8")
        (home / "config.json").chmod(0o600)

        report = writer.remove_connection("prod")

        assert report["already_removed"] is True
        assert report["credential_removed"] is True
        assert not tombstone.exists()


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
