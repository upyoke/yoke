"""One typed command for every non-sensitive key-value setting."""

from __future__ import annotations

import argparse
import json
import sys

from yoke_cli.commands._helpers import (
    add_project_arg,
    add_session_arg,
    add_json_arg,
    client_project_context,
    emit_response,
    usage_error,
)
from yoke_cli.commands.adapters.settings_store import SettingsStore, SettingsCallError
from yoke_cli.config.machine_config_mutation import MachineConfigWriteError
from yoke_contracts.settings_catalog import CATALOG, SCOPES, resolve_setting

_SYNOPSES = {
    "list": "yoke settings list [--scope machine|project|org|universe] [--project P] [--json]",
    "get": "yoke settings get KEY [--project P] [--json]",
    "set": "yoke settings set KEY VALUE [--project P] [--json]",
    "unset": "yoke settings unset KEY [--project P] [--json]",
}
USAGES = {**_SYNOPSES, "set": _SYNOPSES["set"] + " (VALUE - reads JSON from stdin)"}


def run(args, operation):
    parser = argparse.ArgumentParser(
        prog=f"yoke settings {operation}",
        usage=_SYNOPSES[operation],
        description="Machine writes stay local. Project writes require project admin; org and universe writes require org admin. Unset follows defaults. Structured capabilities, environment settings and secrets use their own surfaces.",
    )
    if operation == "list":
        parser.add_argument("--scope", choices=SCOPES, help="List only this scope.")
    else:
        parser.add_argument("key", help="Setting key, as shown by yoke settings list.")
    if operation == "set":
        parser.add_argument(
            "value", help="Typed scalar or JSON document; - reads the value from stdin."
        )
    add_project_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parser.parse_args(args)
    try:
        store = SettingsStore(client_project_context(parsed.project), parsed.session_id)
        if operation == "list":
            result = {
                "settings": [
                    store.read(key)
                    for key, (scope, _) in sorted(CATALOG.items())
                    if not parsed.scope or scope == parsed.scope
                ]
            }
        else:
            _, spec = resolve_setting(parsed.key)
            if operation == "set":
                text = sys.stdin.read() if parsed.value == "-" else parsed.value
                store.write(parsed.key, spec.parse(parsed.key, text))
            elif operation == "unset":
                store.write(parsed.key, unset=True)
            result = store.read(parsed.key)
    except SettingsCallError as exc:
        return emit_response(exc.response, json_mode=parsed.json_mode)
    except (ValueError, OSError, MachineConfigWriteError, RuntimeError) as exc:
        return usage_error(f"{exc}. Recovery: yoke settings list")
    if parsed.json_mode:
        print(json.dumps({"success": True, "result": result}))
    else:
        for row in result.get("settings", [result]):
            print(
                f"{row['key']} ({row['scope']}, {row['source']}): {json.dumps(row['value'])}\n  {row['meaning']}"
            )
    return 0


def list_settings(args):
    return run(args, "list")


def get(args):
    return run(args, "get")


def set_value(args):
    return run(args, "set")


def unset(args):
    return run(args, "unset")
