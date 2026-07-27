"""Typed fixture-operation vocabulary for executable installer recipes."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.machine_qa_fixture_constants import (
    CAMPAIGN_WORKSPACE_PATHS,
    DISTRIBUTION_URL,
    FAKE_TOKEN_PATH,
    HOSTED_PROD_API_URL,
    HOSTED_STAGE_API_URL,
    ONBOARD,
    POST_INSTALL_ONBOARD,
    PROD_TOKEN_PATH,
    STAGE_TOKEN_PATH,
    YOKE_BIN,
)


def operation(operation_id: str, **parameters: Any) -> dict[str, Any]:
    """Build one closed-registry fixture operation reference."""
    return {"id": operation_id, "parameters": parameters}


def workspace_reset() -> dict[str, Any]:
    return operation(
        "installer-campaign.workspace-reset",
        paths=list(CAMPAIGN_WORKSPACE_PATHS),
    )


def prepared_path(*, evidence_name: str) -> dict[str, Any]:
    return operation(
        "machine.path-prepare",
        yoke_bin=YOKE_BIN,
        apply=True,
        evidence_name=evidence_name,
    )


def token_file(
    path: str,
    *,
    state: str,
    source_path: str | None = None,
    restore_after: bool = False,
) -> dict[str, Any]:
    parameters: dict[str, Any] = {
        "path": path,
        "state": state,
        "restore_after": restore_after,
    }
    if source_path is not None:
        parameters["source_path"] = source_path
    return operation("machine.token-file-prepare", **parameters)


def yoke_api(
    *,
    port: int,
    profile: str,
    project_id: int | None = None,
    function_errors: dict[str, Any] | None = None,
    function_delays: dict[str, float] | None = None,
) -> dict[str, Any]:
    parameters: dict[str, Any] = {
        "bind_host": "127.0.0.1",
        "port": port,
        "profile": profile,
        "token_path": FAKE_TOKEN_PATH,
    }
    if project_id is not None:
        parameters["project_id"] = project_id
    if function_errors:
        parameters["function_errors"] = function_errors
    if function_delays:
        parameters["function_delays"] = function_delays
    return operation("fixture.yoke-api-start", **parameters)


def machine_connection(
    *,
    api_url: str,
    token_path: str = FAKE_TOKEN_PATH,
    active_env: str = "stage",
) -> dict[str, Any]:
    return operation(
        "machine.yoke-connection-prepare",
        active_env=active_env,
        api_url=api_url,
        token_path=token_path,
        transport="https" if api_url.startswith("https://") else "http",
    )


def checkout_fixture(
    path: str,
    *,
    state: str = "git-checkout",
    origin: str | None = None,
    readme_text: str = "installer campaign fixture",
) -> dict[str, Any]:
    parameters: dict[str, Any] = {
        "path": path,
        "state": state,
        "default_branch": "main",
        "readme_text": readme_text,
    }
    if origin is not None:
        parameters["origin"] = origin
    return operation("fixture.git-checkout-prepare", **parameters)


def remote_fixture(
    *,
    name: str,
    branch: str,
    path: str,
) -> dict[str, Any]:
    return operation(
        "fixture.git-remote-prepare",
        name=name,
        branch=branch,
        path=path,
        url=f"file://{path}",
    )


def installed_yoke(*, evidence_name: str) -> dict[str, Any]:
    return operation(
        "installer.current-release-prepare",
        base_url=DISTRIBUTION_URL,
        channel="latest",
        no_onboard=True,
        remove_existing_launcher=True,
        evidence_name=evidence_name,
    )


__all__ = [
    "CAMPAIGN_WORKSPACE_PATHS",
    "DISTRIBUTION_URL",
    "FAKE_TOKEN_PATH",
    "HOSTED_PROD_API_URL",
    "HOSTED_STAGE_API_URL",
    "ONBOARD",
    "POST_INSTALL_ONBOARD",
    "PROD_TOKEN_PATH",
    "STAGE_TOKEN_PATH",
    "YOKE_BIN",
    "checkout_fixture",
    "installed_yoke",
    "machine_connection",
    "operation",
    "prepared_path",
    "remote_fixture",
    "token_file",
    "workspace_reset",
    "yoke_api",
]
