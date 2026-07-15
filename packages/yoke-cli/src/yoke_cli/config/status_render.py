"""Rendering helpers for product-wheel ``yoke status``."""

from __future__ import annotations

import json
from typing import Any, Mapping

from yoke_cli.config import install_binding
from yoke_contracts.machine_config import schema as contract


def render_human(report: Mapping[str, Any]) -> str:
    lines = [
        "Yoke status",
        f"  ok: {str(report.get('ok')).lower()}",
        f"  config: {report.get('config_path')}",
        f"  checkout: {report.get('repo_root')}",
    ]
    install = report.get("install")
    if isinstance(install, Mapping):
        lines.append(f"  install: {install_binding.label(install)}")
    server = report.get("server") or {}
    if isinstance(server, Mapping) and server.get("relevant"):
        if server.get("reachable") is True:
            engine = server.get("engine_version") or "<not advertised>"
            authority = server.get("authority") or "<unknown>"
            actor = server.get("actor") or {}
            actor_label = (
                actor.get("label") or actor.get("id") or "<unverified>"
                if isinstance(actor, Mapping)
                else "<unverified>"
            )
            identity = (
                str(actor_label)
                if server.get("identity_verified") is True
                else "<unverified>"
            )
            lines.append(
                f"  server: engine={engine} authority={authority} identity={identity}"
            )
        elif server.get("reachable") is False:
            lines.append("  server: unreachable (engine version unknown)")
        else:
            lines.append("  server: not probed")
    connection = report.get("connection") or {}
    if isinstance(connection, Mapping):
        prod = connection.get(contract.PROD_FLAG_KEY)
        prod_label = str(prod).lower() if isinstance(prod, bool) else "<unset>"
        lines.append(
            "  connection: "
            f"env={connection.get('env') or '<missing>'} "
            f"transport={connection.get('transport') or '<missing>'} "
            f"prod={prod_label} "
            f"credential={connection.get('credential_source', {}).get('kind') or '<missing>'} "
            f"envs={','.join(connection.get('envs') or []) or '<none>'}"
        )
    project = report.get("project") or {}
    if isinstance(project, Mapping):
        lines.append(
            "  project: "
            f"id={project.get('project_id') or '<missing>'} "
            f"scope={project.get('board_scope') or '<missing>'} "
            f"board={project.get('board_render_path') or '<missing>'}"
        )
    runtime = report.get("runtime") or {}
    if isinstance(runtime, Mapping):
        lines.append(
            "  runtime: "
            f"python={runtime.get('python_version')} "
            f"yoke={runtime.get('yoke_executable') or '<not on PATH>'}"
        )
    db = report.get("db") or {}
    if isinstance(db, Mapping):
        lines.append(
            "  db: "
            f"relevant={db.get('relevant')} "
            f"ok={db.get('ok')} "
            f"action={db.get('action') or '<none>'}"
        )
    issues = list(report.get("issues") or [])
    if issues:
        lines.append("  issues:")
        for issue in issues:
            hint = f" Hint: {issue['hint']}" if issue.get("hint") else ""
            lines.append(
                f"    - [{issue['severity']}] {issue['code']}: "
                f"{issue['message']}{hint}"
            )
    else:
        lines.append("  issues: none")
    return "\n".join(lines) + "\n"


def dumps_json(report: Mapping[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


__all__ = ["dumps_json", "render_human"]
