"""Render the non-secret db-admin setup plan and result."""

import json
from pathlib import Path
from typing import Any, Mapping


def dumps_json(report: Mapping[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def render_human(report: Mapping[str, Any]) -> str:
    env = report["environment"]
    lines = [
        "Yoke db-admin setup",
        f"  target: {report['project']}/{env['name']}",
        f"  admin env: {report['plan']['admin_env']}",
        f"  applied: {str(report['applied']).lower()}",
        "",
        "Write plan:",
    ]
    for step in report["plan"]["steps"]:
        lines.append(f"  - {step['action']}: {step['target']}")
    if not report["applied"]:
        lines.extend(["", "Rerun with --yes to apply this plan."])
    lines.append("")
    return "\n".join(lines)


def environment_summary(env: Any) -> dict[str, str]:
    return {
        "project": str(env.project),
        "name": str(env.env_name),
        "activation_state": str(env.activation_state),
        "stack_name": str(env.stack_name),
        "database_name": str(env.database_name),
        "origin_host": str(env.origin_host),
        "ssh_target": str(env.ssh_target),
        "aws_region": str(env.aws_region),
    }


def _path_ref(path: Path) -> str:
    resolved = path.expanduser()
    default_home = Path.home() / ".yoke"
    try:
        rel = resolved.relative_to(default_home)
    except ValueError:
        return str(resolved)
    return "~/.yoke/" + rel.as_posix()
