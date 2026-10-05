"""yoke operations cli db admin identity regression coverage."""

# ruff: noqa: F401
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from yoke_cli import main as yoke_operations_cli
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
)

from runtime.api.cli.test_yoke_operations_cli_dev_db_admin_setup import (
    _env,
    _identity_response,
    pytestmark,
)


def test_control_plane_identity_uses_explicit_named_https_not_active_local(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from yoke_cli.config import db_admin_setup as config

    config_path = tmp_path / "custom-config.json"
    token_path = tmp_path / "tenant.token"
    token_path.write_text("sensitive-token\n", encoding="utf-8")
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "local-admin",
                "connections": {
                    "local-admin": {
                        "transport": "local-postgres",
                        "postgres": {"host": "127.0.0.1", "port": 5432},
                    },
                    "tenant-prod": {
                        "transport": "https",
                        "api_url": "https://tenant.example.com",
                        "credential_source": {
                            "kind": "token_file",
                            "path": str(token_path),
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    observed = {}

    def relay(request, connection):
        observed["request"] = request
        observed["connection"] = connection
        return _identity_response("yoke_tenant_4")

    monkeypatch.setattr(config.https_transport, "relay_https", relay)

    selected = config._select_control_plane_env(
        "prod",
        control_plane_env="tenant-prod",
        config_path=config_path,
    )
    database = config._resolve_control_plane_database(
        selected,
        config_path=config_path,
    )

    assert selected == "tenant-prod"
    assert database == "yoke_tenant_4"
    assert observed["connection"].env == "tenant-prod"
    assert observed["request"].function == "db.read.run"
    assert observed["request"].payload == {"sql": "SELECT current_database()"}


def test_default_control_plane_env_requires_same_label_https(
    tmp_path: Path,
) -> None:
    from yoke_cli.config import db_admin_setup as config

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "tenant-prod",
                "connections": {
                    "prod": {
                        "transport": "local-postgres",
                        "postgres": {"host": "127.0.0.1", "port": 5432},
                    },
                    "tenant-prod": {
                        "transport": "https",
                        "api_url": "https://tenant.example.com",
                        "credential_source": {
                            "kind": "token_file",
                            "path": str(tmp_path / "token"),
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(config.DbAdminSetupError, match="not HTTPS"):
        config._select_control_plane_env(
            "prod",
            control_plane_env=None,
            config_path=config_path,
        )


def test_control_plane_binding_refusal_does_not_write_custom_config(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from yoke_cli.config import db_admin_setup as config

    config_path = tmp_path / "custom-config.json"
    original = {
        "schema_version": 1,
        "active_env": "local-admin",
        "connections": {
            "local-admin": {
                "transport": "local-postgres",
                "postgres": {"host": "127.0.0.1", "port": 5432},
            }
        },
    }
    config_path.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(
        config,
        "_resolve_environment",
        lambda project, env_name: _env(project=project, env_name=env_name),
    )

    rc = yoke_operations_cli.main(
        [
            "dev",
            "db-admin",
            "setup",
            "prod",
            "--control-plane-env",
            "local-admin",
            "--config",
            str(config_path),
            "--yes",
        ]
    )

    assert rc == 1
    assert "not HTTPS" in capsys.readouterr().err
    assert json.loads(config_path.read_text(encoding="utf-8")) == original


def test_control_plane_identity_redacts_transport_token(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from yoke_cli.config import db_admin_setup as config
    from yoke_cli.transport.https import HttpsConnection

    token = "sensitive-token"
    monkeypatch.setattr(
        config.https_transport,
        "resolve_https_connection",
        lambda path, explicit_env=None: HttpsConnection(
            api_url="https://tenant.example.com",
            token=token,
            env=explicit_env or "",
        ),
    )
    monkeypatch.setattr(
        config.https_transport,
        "relay_https",
        lambda request, connection: (_ for _ in ()).throw(
            RuntimeError(f"transport rejected {token}")
        ),
    )

    with pytest.raises(config.DbAdminSetupError) as caught:
        config._resolve_control_plane_database(
            "tenant-prod",
            config_path=tmp_path / "custom-config.json",
        )

    assert token not in str(caught.value)
    assert "<redacted>" in str(caught.value)


@pytest.mark.parametrize(
    "response",
    [
        _identity_response("yoke_tenant_4", columns=["database"]),
        _identity_response("yoke_tenant_4", rows=[]),
        _identity_response("", rows=[[""]]),
        _identity_response("yoke_tenant_4", rows=[["one"], ["two"]]),
        _identity_response("yoke_tenant_4", truncated=True),
        FunctionCallResponse(
            success=False,
            function="db.read.run",
            version="v1",
            error=FunctionError(code="permission_denied", message="denied"),
        ),
    ],
)
def test_control_plane_identity_refuses_non_exact_response(
    tmp_path: Path,
    monkeypatch,
    response: FunctionCallResponse,
) -> None:
    from yoke_cli.config import db_admin_setup as config
    from yoke_cli.transport.https import HttpsConnection

    monkeypatch.setattr(
        config.https_transport,
        "resolve_https_connection",
        lambda path, explicit_env=None: HttpsConnection(
            api_url="https://tenant.example.com",
            token="sensitive-token",
            env=explicit_env or "",
        ),
    )
    monkeypatch.setattr(
        config.https_transport,
        "relay_https",
        lambda request, connection: response,
    )

    with pytest.raises(config.DbAdminSetupError):
        config._resolve_control_plane_database(
            "tenant-prod",
            config_path=tmp_path / "custom-config.json",
        )
