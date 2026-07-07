"""Import-boundary tests for the extracted CLI transport dispatcher."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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
