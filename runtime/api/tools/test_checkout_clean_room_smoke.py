from __future__ import annotations

import json
from pathlib import Path

from yoke_contracts.machine_config import schema as contract
from yoke_core.tools import checkout_clean_room_smoke as smoke


def test_build_machine_config_uses_code_owned_example(tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    clone.mkdir()
    dsn = tmp_path / "home" / ".yoke" / "secrets" / "authority.dsn"
    payload = smoke.build_machine_config(
        example_payload=contract.canonical_example_payload(),
        clone_root=clone,
        copied_dsn=dsn,
        temp_root=tmp_path / "home" / ".yoke" / "tmp",
        cache_dir=tmp_path / "home" / ".yoke" / "cache",
        env_name="prod",
        project_id=1,
    )

    assert payload["schema_version"] == contract.SCHEMA_VERSION
    assert payload["active_env"] == "prod"
    assert payload["connections"]["prod"]["transport"] == "local-postgres"
    assert payload["connections"]["prod"]["credential_source"] == {
        "kind": "dsn_file",
        "path": str(dsn),
    }
    assert payload["projects"] == [
        {
            "checkout": str(clone.resolve()),
            "project_id": 1,
            "env": "prod",
            "board": {"render_path": ".yoke/BOARD.md", "scope": "1"},
        }
    ]


def test_write_machine_files_owner_only(tmp_path: Path) -> None:
    source_dsn = tmp_path / "source.dsn"
    source_dsn.write_text("host=127.0.0.1 dbname=yoke\n", encoding="utf-8")
    machine_home = tmp_path / "home" / ".yoke"
    config_path = machine_home / "config.json"
    copied_dsn = machine_home / "secrets" / "authority.dsn"

    smoke._write_machine_files(
        machine_home=machine_home,
        secrets_dir=machine_home / "secrets",
        config_path=config_path,
        copied_dsn=copied_dsn,
        source_dsn=source_dsn,
        payload={"schema_version": 1, "connections": {}, "projects": {}},
    )

    assert json.loads(config_path.read_text(encoding="utf-8"))["schema_version"] == 1
    assert config_path.stat().st_mode & 0o077 == 0
    assert copied_dsn.stat().st_mode & 0o077 == 0
    assert copied_dsn.read_text(encoding="utf-8") == "host=127.0.0.1 dbname=yoke\n"


def test_isolated_env_drops_ambient_db_credentials(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YOKE_PG_DSN", "secret")
    env = smoke._isolated_env(
        home=tmp_path / "home",
        machine_home=tmp_path / "home" / ".yoke",
        config_path=tmp_path / "home" / ".yoke" / "config.json",
        venv_bin=tmp_path / "venv" / "bin",
        env_name="prod",
        session_id="session",
    )

    assert "YOKE_PG_DSN" not in env
    assert "YOKE_PG_DSN_FILE" not in env
    assert env["YOKE_MACHINE_CONFIG_FILE"].endswith("config.json")
    assert env["PATH"].startswith(str(tmp_path / "venv" / "bin"))


def test_clean_clone_shape_refuses_retired_authority_dirs(tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    (clone / "data").mkdir(parents=True)

    try:
        smoke._assert_clean_clone_shape(clone)
    except smoke.SmokeError as exc:
        assert "data" in str(exc)
    else:
        raise AssertionError("expected clean clone check to reject data/")
