"""Import-boundary tests for the extracted CLI transport dispatcher."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from runtime.api.product_boundary_isolation import write_sitecustomize


def _client_only_env(tmp_path: Path) -> dict[str, str]:
    root = Path(__file__).resolve().parents[3]
    env = os.environ.copy()
    cli_src = root / "packages" / "yoke-cli" / "src"
    contracts_src = root / "packages" / "yoke-contracts" / "src"
    sitecustomize_dir = write_sitecustomize(
        tmp_path,
        repo_root=root,
        allowed_repo_paths=(cli_src, contracts_src),
    )
    env["PYTHONPATH"] = os.pathsep.join(
        [str(sitecustomize_dir), str(cli_src), str(contracts_src)]
    )
    return env


def test_dispatcher_import_does_not_load_core_runtime_or_psycopg(
    tmp_path: Path,
) -> None:
    script = """
import json
import sys
import yoke_cli.transport.dispatcher
forbidden = sorted(
    name for name in sys.modules
    if name == "runtime" or name.startswith("runtime.")
    or name == "yoke_core" or name.startswith("yoke_core.")
    or name == "psycopg" or name.startswith("psycopg.")
)
print(json.dumps(forbidden))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd="/tmp",
        env=_client_only_env(tmp_path),
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == []


def test_local_dispatch_without_core_fails_closed(tmp_path: Path) -> None:
    script = """
import json
from yoke_contracts.api.function_call import TargetRef
from yoke_cli.transport.dispatcher import call_dispatcher

response = call_dispatcher(
    function_id="events.query.run",
    target=TargetRef(kind="global"),
    local_only=True,
)
print(json.dumps(response.model_dump(mode="json"), sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd="/tmp",
        env=_client_only_env(tmp_path),
        capture_output=True,
        text=True,
        check=True,
    )
    response = json.loads(result.stdout)
    assert response["success"] is False
    assert response["error"]["code"] == "local_postgres_core_unavailable"


def test_local_dispatch_allows_explicit_prod_flag_when_local_core_is_available(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "schema_version": 1,
            "active_env": "prod-db-admin",
            "connections": {
                "prod-db-admin": {
                    "transport": "local-postgres",
                    "prod": True,
                },
            },
        }),
        encoding="utf-8",
    )
    env = _client_only_env(tmp_path)
    env["YOKE_MACHINE_CONFIG_FILE"] = str(config_path)
    script = """
import json
from yoke_contracts.api.function_call import TargetRef
from yoke_cli.transport.dispatcher import call_dispatcher

def local_dispatch(_request):
    from yoke_contracts.api.function_call import FunctionCallResponse
    return FunctionCallResponse(
        success=True,
        function=_request.function,
        version=_request.version,
        request_id=_request.request_id,
        result={"transport": "local-postgres", "env": "prod-db-admin"},
    )

response = call_dispatcher(
    function_id="events.query.run",
    target=TargetRef(kind="global"),
    local_only=True,
    _local_dispatch=local_dispatch,
)
print(json.dumps(response.model_dump(mode="json"), sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd="/tmp",
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    response = json.loads(result.stdout)
    assert response["success"] is True
    assert response["result"] == {
        "transport": "local-postgres",
        "env": "prod-db-admin",
    }


def test_local_dispatch_allows_prod_shaped_names_without_explicit_flag(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "schema_version": 1,
            "active_env": "prod",
            "connections": {
                "prod": {
                    "transport": "local-postgres",
                    "authority": {
                        "location": {
                            "stack": "yoke-prod",
                            "database_name": "yoke_prod",
                        },
                    },
                },
            },
        }),
        encoding="utf-8",
    )
    env = _client_only_env(tmp_path)
    env["YOKE_MACHINE_CONFIG_FILE"] = str(config_path)
    script = """
import json
from yoke_contracts.api.function_call import FunctionCallResponse, TargetRef
from yoke_cli.transport.dispatcher import call_dispatcher

def local_dispatch(request):
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={"transport": "local-postgres"},
    )

response = call_dispatcher(
    function_id="events.query.run",
    target=TargetRef(kind="global"),
    _local_dispatch=local_dispatch,
)
print(json.dumps(response.model_dump(mode="json"), sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd="/tmp",
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    response = json.loads(result.stdout)
    assert response["success"] is True
    assert response["result"] == {"transport": "local-postgres"}


def test_local_dispatch_binds_lazy_machine_github_authorization(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from yoke_cli.config import github_user_tokens, machine_config
    from yoke_cli.transport.dispatcher import call_dispatcher
    from yoke_contracts.api.function_call import FunctionCallResponse, TargetRef
    from yoke_core.domain.github_app_dispatch_context import (
        LOCAL_API_ENDPOINT,
        LOCAL_USER_TOKEN_PROVIDER,
    )

    monkeypatch.setattr(
        machine_config,
        "github_config",
        lambda: {"api_url": "https://github.example/api/v3"},
    )
    token_reads: list[bool] = []

    def _token():
        token_reads.append(True)
        return SimpleNamespace(access_token="local-user-token")

    monkeypatch.setattr(
        github_user_tokens,
        "access_token_from_machine_config",
        _token,
    )

    def _local_dispatch(request):
        endpoint = LOCAL_API_ENDPOINT.get()
        provider = LOCAL_USER_TOKEN_PROVIDER.get()
        assert endpoint is not None
        assert endpoint.base_url == "https://github.example/api/v3"
        assert provider is not None
        assert token_reads == []
        assert provider() == "local-user-token"
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={"bound": True},
        )

    response = call_dispatcher(
        function_id="projects.github_binding.status",
        target=TargetRef(kind="global"),
        local_only=True,
        _local_dispatch=_local_dispatch,
    )

    assert response.success is True
    assert token_reads == [True]
    assert LOCAL_API_ENDPOINT.get() is None
    assert LOCAL_USER_TOKEN_PROVIDER.get() is None


def test_invalid_machine_github_endpoint_does_not_block_unrelated_dispatch(
    monkeypatch,
) -> None:
    from yoke_cli.config import machine_config
    from yoke_cli.transport.dispatcher import call_dispatcher
    from yoke_contracts.api.function_call import FunctionCallResponse, TargetRef
    from yoke_core.domain.github_app_dispatch_context import LOCAL_USER_TOKEN_PROVIDER

    monkeypatch.setattr(
        machine_config,
        "github_config",
        lambda: {"api_url": "http://unsafe.example"},
    )

    def _local_dispatch(request):
        provider = LOCAL_USER_TOKEN_PROVIDER.get()
        assert provider is not None
        with pytest.raises(RuntimeError, match="configuration is invalid"):
            provider()
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={"unrelated": True},
        )

    response = call_dispatcher(
        function_id="events.query.run",
        target=TargetRef(kind="global"),
        local_only=True,
        _local_dispatch=_local_dispatch,
    )

    assert response.success is True
    assert response.result == {"unrelated": True}
