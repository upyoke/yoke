# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

from types import SimpleNamespace

import pytest

from yoke_cli import main as yoke_operations_cli

from runtime.api.cli.test_db_admin_box_hop import MAC_FINGERPRINT

from yoke_contracts.api.function_call import (
    FunctionCallResponse,
)

pytestmark = pytest.mark.usefixtures("bound_project_context")


def _identity_response(
    database: str,
    *,
    columns=None,
    rows=None,
    truncated: bool = False,
) -> FunctionCallResponse:
    selected_rows = [[database]] if rows is None else rows
    return FunctionCallResponse(
        success=True,
        function="db.read.run",
        version="v1",
        result={
            "columns": ["current_database"] if columns is None else columns,
            "rows": selected_rows,
            "row_count": len(selected_rows),
            "row_cap": 100,
            "truncated": truncated,
            "statement_timeout_ms": 5000,
        },
    )


def _env(
    *,
    project: str = "yoke",
    env_name: str = "stage",
    activation_state: str = "active",
) -> SimpleNamespace:
    return SimpleNamespace(
        project=project,
        env_name=env_name,
        activation_state=activation_state,
        stack_name=f"yoke-{env_name}",
        database_name=f"yoke_{env_name}",
        origin_host=f"origin.{env_name}.example.com",
        ssh_key_path=f"/tmp/yoke-{env_name}.pem",
        ssh_target=f"ubuntu@origin.{env_name}.example.com",
        aws_region="us-east-1",
        ssh_user="ubuntu",
        mac_host="testy@mac-mini",
        mac_host_ssh_key_path="~/.ssh/operator_rsa",
        mac_host_key_fingerprint=MAC_FINGERPRINT,
    )
