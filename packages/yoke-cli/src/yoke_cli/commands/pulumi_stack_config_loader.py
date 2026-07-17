"""Load sensitive stack config outside the generic function response ledger."""

from __future__ import annotations

import importlib
from typing import Any, Mapping
from urllib.parse import quote
import urllib.request

from yoke_cli.api_urls import join_api_url
from yoke_cli.transport.bounded_json_http import request_json
from yoke_cli.transport.https import resolve_https_connection


def load_pulumi_stack_config(project: str, stack: str) -> Mapping[str, Any]:
    """Use the admin HTTP download boundary or local core materializer."""
    connection = resolve_https_connection()
    if connection is not None:
        url = join_api_url(
            connection.api_url,
            "/v1/projects/"
            f"{quote(project, safe='')}/pulumi-stack-config/"
            f"{quote(stack, safe='')}",
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
            allow_loopback_http=True,
            sensitive_values=(connection.token,),
        )
        if not isinstance(response.payload, Mapping):
            raise RuntimeError("Pulumi stack config response must be an object")
        return response.payload
    db_helpers = importlib.import_module("yoke_core.domain.db_helpers")
    renderer = importlib.import_module(
        "yoke_core.domain.project_renderer_pulumi_stack_config"
    )
    conn = db_helpers.connect()
    try:
        return renderer.build_pulumi_stack_config(conn, project, stack)
    finally:
        conn.close()


__all__ = ["load_pulumi_stack_config"]
