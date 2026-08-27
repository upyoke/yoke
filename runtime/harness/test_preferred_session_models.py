"""Preferred-model map resolution and machine-config validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import db_backend, machine_config, machine_config_status
from yoke_core.domain import yoke_connected_env
from yoke_cli.config import machine_config_mutation
from yoke_contracts.machine_config.preferred_session_models import (
    EXPLICIT_SOURCE,
    PREFERRED_SESSION_MODELS_KEY,
    VENDOR_DEFAULT_SOURCE,
    blank_preferred_session_models,
    launchable_preferred_surfaces,
    list_preferred_models,
    preferred_session_models,
    render_list_models,
    resolve_launch_model,
    seed_preferred_session_models,
    validate_preferred_session_models,
)
from yoke_contracts.machine_config import schema as contract
from yoke_contracts.session_control.capabilities import SESSION_SURFACE_CAPABILITIES
from yoke_cli.config import status_render


def test_explicit_model_outranks_preferred_map() -> None:
    payload = {PREFERRED_SESSION_MODELS_KEY: {"cursor-cli": "preferred-model"}}

    resolved = resolve_launch_model("explicit-model", "cursor-cli", payload=payload)

    assert resolved.model == "explicit-model"
    assert resolved.source == EXPLICIT_SOURCE


def test_preferred_map_outranks_vendor_default() -> None:
    payload = {PREFERRED_SESSION_MODELS_KEY: {"cursor-cli": "preferred-model"}}

    resolved = resolve_launch_model(None, "cursor-cli", payload=payload)

    assert resolved.model == "preferred-model"
    assert resolved.source == f"{PREFERRED_SESSION_MODELS_KEY}.cursor-cli"


def test_missing_surface_falls_through_to_vendor_default() -> None:
    payload = {PREFERRED_SESSION_MODELS_KEY: {"claude-cli": "claude-opus"}}

    resolved = resolve_launch_model("", "cursor-cli", payload=payload)

    assert resolved.model is None
    assert resolved.source == VENDOR_DEFAULT_SOURCE


def test_blank_and_whitespace_values_are_unset() -> None:
    payload = {
        PREFERRED_SESSION_MODELS_KEY: {
            "cursor-cli": "",
            "claude-cli": "   ",
            "codex-cli": "codex-model",
        }
    }

    assert preferred_session_models(payload) == {"codex-cli": "codex-model"}
    assert validate_preferred_session_models(payload) == []
    blank = resolve_launch_model(None, "cursor-cli", payload=payload)
    whitespace = resolve_launch_model(None, "claude-cli", payload=payload)
    assert blank.model is None and blank.source == VENDOR_DEFAULT_SOURCE
    assert whitespace.model is None and whitespace.source == VENDOR_DEFAULT_SOURCE


def test_non_string_model_is_rejected_by_machine_config() -> None:
    payload = contract.canonical_example_payload()
    payload[PREFERRED_SESSION_MODELS_KEY] = {"cursor-cli": 12}

    issues = validate_preferred_session_models(payload)
    full = contract.validate_payload(payload)

    assert any(
        issue.code == "preferred_session_models_model_invalid" for issue in issues
    )
    assert any(issue.code == "preferred_session_models_model_invalid" for issue in full)


def test_canonical_example_seeds_blank_launchable_surfaces() -> None:
    payload = contract.canonical_example_payload()
    seeded = payload[PREFERRED_SESSION_MODELS_KEY]
    launchable = launchable_preferred_surfaces()

    assert set(seeded) == set(launchable)
    assert all(value == "" for value in seeded.values())
    assert contract.validate_payload(payload) == []
    assert "claude-cli" in launchable
    assert "codex-cli" in launchable
    assert "cursor-cli" in launchable
    assert all(
        SESSION_SURFACE_CAPABILITIES[surface].create == "supported"
        for surface in launchable
    )


def test_seed_does_not_overwrite_existing_map() -> None:
    payload = {PREFERRED_SESSION_MODELS_KEY: {"cursor-cli": "kept-model"}}

    assert seed_preferred_session_models(payload) is False
    assert payload[PREFERRED_SESSION_MODELS_KEY] == {"cursor-cli": "kept-model"}


def test_list_models_treats_blanks_as_absent(monkeypatch, tmp_path) -> None:
    config = tmp_path / "config.json"
    monkeypatch.setattr(
        "yoke_contracts.machine_config.runtime.load_config",
        lambda path=None: {
            PREFERRED_SESSION_MODELS_KEY: blank_preferred_session_models()
        },
    )
    monkeypatch.setattr(
        "yoke_contracts.machine_config.runtime.config_path",
        lambda: config,
    )

    report = list_preferred_models("cursor-cli")
    rendered = render_list_models(report, json_mode=False)

    assert report["key"] == PREFERRED_SESSION_MODELS_KEY
    assert report["config_file"] == str(config)
    assert report["entries"] == []
    assert report["selected"]["model"] is None
    assert report["selected"]["source"] == VENDOR_DEFAULT_SOURCE
    assert PREFERRED_SESSION_MODELS_KEY in rendered
    assert "(no preferred models configured)" in rendered


def test_list_models_names_the_config_key_as_source(monkeypatch, tmp_path) -> None:
    config = tmp_path / "config.json"
    monkeypatch.setattr(
        "yoke_contracts.machine_config.runtime.load_config",
        lambda path=None: {
            PREFERRED_SESSION_MODELS_KEY: {"cursor-cli": "preferred-model"}
        },
    )
    monkeypatch.setattr(
        "yoke_contracts.machine_config.runtime.config_path",
        lambda: config,
    )

    report = list_preferred_models("cursor-cli")
    rendered = render_list_models(report, json_mode=False)

    assert report["key"] == PREFERRED_SESSION_MODELS_KEY
    assert report["selected"]["source"] == f"{PREFERRED_SESSION_MODELS_KEY}.cursor-cli"
    assert "preferred-model" in rendered
    assert f"{PREFERRED_SESSION_MODELS_KEY}.cursor-cli" in rendered


def test_fresh_load_payload_seeds_blanks_without_writing(tmp_path) -> None:
    config = tmp_path / "config.json"

    payload, loaded = machine_config_mutation.load_payload(config)

    assert loaded == config
    assert not config.exists()
    assert payload[PREFERRED_SESSION_MODELS_KEY] == blank_preferred_session_models()


def test_existing_config_without_key_is_not_backfilled(tmp_path) -> None:
    config = tmp_path / "config.json"
    existing = {"schema_version": 1, "active_env": "prod"}
    config.write_text(json.dumps(existing), encoding="utf-8")

    payload, _loaded = machine_config_mutation.load_payload(config)

    assert PREFERRED_SESSION_MODELS_KEY not in payload
    assert json.loads(config.read_text(encoding="utf-8")) == existing


def test_explicit_repair_seeds_missing_key_on_existing_config(tmp_path) -> None:
    config = tmp_path / "config.json"
    payload = contract.canonical_example_payload()
    del payload[PREFERRED_SESSION_MODELS_KEY]
    config.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    result = machine_config_mutation.repair_preferred_session_models(path=config)
    written = json.loads(config.read_text(encoding="utf-8"))

    assert result["seeded"] is True
    assert written[PREFERRED_SESSION_MODELS_KEY] == blank_preferred_session_models()


def test_status_names_the_preferred_models_key() -> None:
    rendered = status_render.render_human({"config_path": "/tmp/config.json"})

    assert (
        f"  {PREFERRED_SESSION_MODELS_KEY}: blank = unset in /tmp/config.json"
        in rendered
    )


def _seeded_blank_binding(root: Path, dsn_file: Path) -> Path:
    """Write a machine config whose preferred-model map is freshly seeded."""
    path = root / ".yoke" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "local",
                "connections": {
                    "local": {
                        "transport": "local-postgres",
                        "credential_source": {
                            "kind": "dsn_file",
                            "path": str(dsn_file),
                        },
                    },
                },
                "projects": {str(root.resolve()): {"project_id": 1}},
                PREFERRED_SESSION_MODELS_KEY: blank_preferred_session_models(),
            }
        ),
        encoding="utf-8",
    )
    return path


def _bind_config(monkeypatch, config: Path, cwd: Path) -> None:
    for key in (
        db_backend.PG_DSN_ENV,
        db_backend.PG_DSN_FILE_ENV,
        "YOKE_DB",
        machine_config.CONFIG_FILE_ENV,
        yoke_connected_env.DISABLE_ENV,
        yoke_connected_env.PYTEST_ENABLE_ENV,
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(config))
    monkeypatch.chdir(cwd)


def test_seeded_blank_map_resolves_postgres_credentials(monkeypatch, tmp_path) -> None:
    dsn_file = tmp_path / "local.dsn"
    dsn_file.write_text("host=127.0.0.1 dbname=yoke\n", encoding="utf-8")
    repo = tmp_path / "repo"
    config = _seeded_blank_binding(repo, dsn_file)
    _bind_config(monkeypatch, config, repo)

    active = yoke_connected_env.load_active()
    resolved = yoke_connected_env.resolve_postgres_dsn(
        dsn_env=db_backend.PG_DSN_ENV,
        dsn_file_env=db_backend.PG_DSN_FILE_ENV,
    )

    assert active is not None and active.backend == db_backend.POSTGRES
    assert resolved.dsn.startswith("host=127.0.0.1")


def test_non_string_model_still_fails_credential_resolution(monkeypatch, tmp_path):
    dsn_file = tmp_path / "local.dsn"
    dsn_file.write_text("host=127.0.0.1 dbname=yoke\n", encoding="utf-8")
    repo = tmp_path / "repo"
    config = _seeded_blank_binding(repo, dsn_file)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload[PREFERRED_SESSION_MODELS_KEY]["cursor-cli"] = 7
    config.write_text(json.dumps(payload), encoding="utf-8")
    _bind_config(monkeypatch, config, repo)

    with pytest.raises(
        yoke_connected_env.ConnectedEnvError, match=PREFERRED_SESSION_MODELS_KEY
    ):
        yoke_connected_env.load_active()


def test_config_status_agrees_with_the_validator_on_a_seeded_map(tmp_path) -> None:
    config = tmp_path / "config.json"
    payload = contract.canonical_example_payload()
    config.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    report = machine_config_status.build_status(
        config_path=config,
        repo_root=tmp_path,
        check_reachability=False,
    )
    reported = [
        issue
        for issue in report["issues"]
        if PREFERRED_SESSION_MODELS_KEY in issue.get("message", "")
    ]

    assert payload[PREFERRED_SESSION_MODELS_KEY] == blank_preferred_session_models()
    assert validate_preferred_session_models(payload) == []
    assert reported == []
