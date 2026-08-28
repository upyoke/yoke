"""Machine-config adapters for the ``yoke`` CLI."""

from __future__ import annotations

import argparse
from typing import Any, List

from yoke_cli.commands._helpers import (
    attach_field_note_footer,
    parse_or_usage_error,
)
from yoke_cli.config import status as machine_config_status
from yoke_contracts.connection_authority_teaching import (
    ENV_LIST_AUTHORITY_FOOTER,
)
from yoke_contracts.machine_config import schema as machine_config_contract


CONFIG_EXAMPLE_USAGE = "yoke config example"
STATUS_USAGE = "yoke status [--config PATH] [--repo-root PATH] [--env NAME] [--json]"
CONFIG_STATUS_USAGE = (
    "yoke config status [--config PATH] [--repo-root PATH] [--env NAME] [--json]"
)
ENV_LIST_USAGE = "yoke env list [--config PATH] [--json]"


def env_list(args: List[str]) -> int:
    from yoke_cli.config import machine_config

    parser = argparse.ArgumentParser(prog="yoke env list")
    parser.add_argument("--config", dest="config_path", default=None)
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, ENV_LIST_USAGE)
    if parsed is None:
        return 2
    payload = machine_config.load_config(parsed.config_path)
    connections = payload.get("connections")
    connections = connections if isinstance(connections, dict) else {}
    active = str(payload.get("active_env") or "")
    rows: list[dict[str, Any]] = [
        {
            "env": str(name),
            "active": str(name) == active,
            "transport": str(entry.get("transport") or ""),
            "prod": bool(entry.get("prod", False)),
            "api_url": str(entry.get("api_url") or ""),
        }
        for name, entry in sorted(connections.items())
        if isinstance(entry, dict)
    ]
    if parsed.json_mode:
        import json

        print(json.dumps({"active_env": active, "rows": rows}, sort_keys=True))
    else:
        for row in rows:
            print(
                f"{row['env']}|{str(row['active']).lower()}|"
                f"{row['transport']}|{str(row['prod']).lower()}|{row['api_url']}"
            )
        print(ENV_LIST_AUTHORITY_FOOTER)
    return 0


def config_example(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog=CONFIG_EXAMPLE_USAGE)
    attach_field_note_footer(parser)
    parsed = parse_or_usage_error(parser, args, CONFIG_EXAMPLE_USAGE)
    if parsed is None:
        return 2
    print(machine_config_contract.canonical_example_text(), end="")
    return 0


def status(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke status")
    parser.add_argument("--config", dest="config_path", default=None)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--env", dest="explicit_env", default=None)
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, STATUS_USAGE)
    if parsed is None:
        return 2
    report = machine_config_status.build_status(
        config_path=parsed.config_path,
        repo_root=parsed.repo_root,
        explicit_env=parsed.explicit_env,
    )
    if parsed.json_mode:
        print(machine_config_status.dumps_json(report), end="")
    else:
        print(machine_config_status.render_human(report), end="")
    return 0 if report.get("ok") else 1


__all__ = [
    "CONFIG_EXAMPLE_USAGE",
    "CONFIG_STATUS_USAGE",
    "ENV_LIST_USAGE",
    "STATUS_USAGE",
    "config_example",
    "env_list",
    "status",
]
