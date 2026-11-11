"""Load the secret-free project settings snapshot over either transport."""

from __future__ import annotations

import importlib
from typing import Any, Mapping
from urllib.parse import quote
import urllib.request

from yoke_cli.api_urls import join_api_url
from yoke_contracts.bounded_json_http import request_json
from yoke_cli.transport.https import resolve_https_connection


def load_project_renderer_settings_snapshot(project: str) -> Mapping[str, Any]:
    """Load the secret-free aggregate renderer snapshot over either transport."""
    connection = resolve_https_connection()
    if connection is not None:
        url = join_api_url(
            connection.api_url,
            f"/v1/projects/{quote(project, safe='')}/pulumi-stack-config",
        )
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"Authorization": f"Bearer {connection.token}"},
        )
        response = request_json(
            request,
            timeout_seconds=30.0,
            replay_safe=True,
            allow_private_http=True,
            sensitive_values=(connection.token,),
        )
        if not isinstance(response.payload, Mapping):
            raise RuntimeError("project renderer settings response must be an object")
        return response.payload
    db_helpers = importlib.import_module("yoke_core.domain.db_helpers")
    snapshots = importlib.import_module(
        "yoke_core.domain.project_renderer_settings_snapshot"
    )
    conn = db_helpers.connect()
    try:
        return snapshots.build_pulumi_stack_config(conn, project)
    finally:
        conn.close()


__all__ = ["load_project_renderer_settings_snapshot"]
