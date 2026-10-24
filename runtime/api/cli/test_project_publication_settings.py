"""Checkout publication settings preserve Git configuration and connection scope."""

import json
from pathlib import Path

from yoke_cli.config import machine_config, writer_projects
from yoke_contracts.machine_config import schema_projects


def seed_project(root, config=None, project_id=7):
    config = Path(config) if config else machine_config.config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(config.read_text()) if config.exists() else {}
    token = config.parent / "test.token"
    token.write_text("fixture-token\n")
    if payload.get("github"):
        payload["github"]["profile_source"] = "local_explicit"
    payload.update(
        {
            "schema_version": 1,
            "active_env": "test",
            "connections": {
                "test": {
                    "transport": "https",
                    "api_url": "https://test.invalid",
                    "credential_source": {"kind": "token_file", "path": str(token)},
                },
            },
        }
    )
    config.write_text(json.dumps(payload))
    writer_projects.register_project(root, project_id, path=config)
    return config


def test_normalization_and_registration_preserve_typed_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("YOKE_ENV", raising=False)
    root = tmp_path / "checkout"
    root.mkdir()
    config = seed_project(root)
    writer_projects.set_publication_read_only(root, True)
    writer_projects.register_project(root, 7)
    assert machine_config.project_entry(root)["publication_read_only"] is True
    payload = json.loads(config.read_text())
    assert (
        schema_projects.project_entry_for_checkout(payload, root / "child")[
            "publication_read_only"
        ]
        is True
    )
    payload["connections"]["other"] = dict(payload["connections"]["test"])
    payload["active_env"] = "other"
    payload["connection_projects"]["other"] = [{"checkout": str(root), "project_id": 7}]
    assert schema_projects.project_entry_for_checkout(payload, root) == {
        "project_id": 7
    }


def test_invalid_setting_is_not_silently_coerced():
    from yoke_contracts.machine_config.schema_project_validation import (
        validate_projects,
    )

    issues = validate_projects(
        [{"checkout": "/project", "project_id": 7, "publication_read_only": "false"}]
    )
    assert any(row.code == "project_publication_read_only_invalid" for row in issues)


def test_registration_ownership_snapshots_policy_and_refuses_missing_mapping(tmp_path, monkeypatch):
    import pytest
    from yoke_cli.project_install import owned_cleanup, files

    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("YOKE_ENV", raising=False)
    root = tmp_path / "checkout"
    root.mkdir()
    config = seed_project(root)
    writer_projects.set_publication_read_only(root, True)
    saved = []
    monkeypatch.setattr(files, "load_manifest", lambda root: {"project_id": 7})
    monkeypatch.setattr(files, "write_manifest", lambda root, manifest: saved.append(manifest))
    owned_cleanup.record_registration(root, 7, config)
    record = saved[0][owned_cleanup.REGISTRATION_KEY]
    assert record["connection"] == "test"
    assert record["entry"] == {"checkout": str(root), "project_id": 7, "publication_read_only": True}
    with pytest.raises(files.ProjectInstallError, match="ownership_unproven"):
        owned_cleanup.record_registration(root, 8, config)
    assert len(saved) == 1
