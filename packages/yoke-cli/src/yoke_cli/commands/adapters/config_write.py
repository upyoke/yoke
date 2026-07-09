"""Machine-config writer adapters for the ``yoke`` CLI.

Sibling of :mod:`yoke_cli.commands.adapters.config` (read-side diagnostics).
The env arg is positional on every writer because the CLI's global
``--env`` flag is extracted before adapters parse — a writer flag named
``--env`` would be swallowed by per-command env routing.
"""

from __future__ import annotations

import argparse
import json
from typing import List

from yoke_cli.commands._helpers import (
    attach_field_note_footer,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.config import machine_config
from yoke_cli.config import writer


ENV_USE_USAGE = "yoke env use ENV [--config PATH]"
CONNECTION_SET_USAGE = (
    "yoke connection set ENV [--transport {local-postgres,https}] "
    "[--prod | --non-prod] [--api-url URL] "
    "[CREDENTIAL | --token-file PATH | --token-stdin | --dsn DSN | "
    "--dsn-file PATH | --dsn-stdin] [--config PATH]"
)
AUTH_SET_USAGE = (
    "yoke auth set ENV [CREDENTIAL | --token-file PATH | --token-stdin | "
    "--dsn DSN | --dsn-file PATH | --dsn-stdin] [--config PATH]"
)
PROJECT_REGISTER_USAGE = (
    "yoke project register REPO_ROOT --project-id N "
    "[--board-scope SCOPE] [--board-render-path PATH] [--config PATH]"
)
STAMP_PROJECT_ENV_USAGE = (
    "yoke config stamp-project-env [--config PATH]"
)


def env_use(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke env use")
    parser.add_argument("env")
    parser.add_argument("--config", dest="config_path", default=None)
    attach_field_note_footer(parser)
    parsed = parse_or_usage_error(parser, args, ENV_USE_USAGE)
    if parsed is None:
        return 2
    writer = _writer()
    return _run(lambda: writer.set_active_env(
        parsed.env, path=parsed.config_path,
    ))


def connection_set(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke connection set")
    parser.add_argument("env")
    parser.add_argument("credential", nargs="?")
    parser.add_argument("--transport", choices=["local-postgres", "https"],
                        default=None)
    prod_group = parser.add_mutually_exclusive_group()
    prod_group.add_argument("--prod", dest="prod", action="store_true",
                            default=False)
    prod_group.add_argument("--non-prod", dest="non_prod",
                            action="store_true", default=False)
    parser.add_argument("--api-url", dest="api_url", default=None)
    parser.add_argument("--token-file", dest="token_file", default=None)
    parser.add_argument("--token-stdin", dest="token_stdin",
                        action="store_true")
    parser.add_argument("--dsn", dest="dsn", default=None)
    parser.add_argument("--dsn-file", dest="dsn_file", default=None)
    parser.add_argument("--dsn-stdin", dest="dsn_stdin", action="store_true")
    parser.add_argument("--config", dest="config_path", default=None)
    attach_field_note_footer(parser)
    parsed = parse_or_usage_error(parser, args, CONNECTION_SET_USAGE)
    if parsed is None:
        return 2
    if parsed.credential and any((
        parsed.token_file, parsed.token_stdin, parsed.dsn,
        parsed.dsn_file, parsed.dsn_stdin,
    )):
        return usage_error(
            "positional credential is mutually exclusive with credential flags: "
            f"{CONNECTION_SET_USAGE}"
        )
    writer = _writer()
    return _run(lambda: _connection_set(writer, parsed))


def auth_set(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke auth set")
    parser.add_argument("env")
    parser.add_argument("credential", nargs="?")
    parser.add_argument("--token-file", dest="token_file", default=None)
    parser.add_argument("--token-stdin", dest="token_stdin",
                        action="store_true")
    parser.add_argument("--dsn", dest="dsn", default=None)
    parser.add_argument("--dsn-file", dest="dsn_file", default=None)
    parser.add_argument("--dsn-stdin", dest="dsn_stdin", action="store_true")
    parser.add_argument("--config", dest="config_path", default=None)
    attach_field_note_footer(parser)
    parsed = parse_or_usage_error(parser, args, AUTH_SET_USAGE)
    if parsed is None:
        return 2
    if parsed.credential and any((
        parsed.token_file, parsed.token_stdin, parsed.dsn,
        parsed.dsn_file, parsed.dsn_stdin,
    )):
        return usage_error(
            "positional credential is mutually exclusive with credential flags: "
            f"{AUTH_SET_USAGE}"
        )
    writer = _writer()
    return _run(lambda: _auth_set(writer, parsed))


def project_register(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke project register")
    parser.add_argument("repo_root")
    parser.add_argument("--project-id", dest="project_id", type=int,
                        required=True)
    parser.add_argument("--board-scope", dest="board_scope", default=None)
    parser.add_argument("--board-render-path", dest="board_render_path",
                        default=None)
    parser.add_argument("--config", dest="config_path", default=None)
    attach_field_note_footer(parser)
    parsed = parse_or_usage_error(parser, args, PROJECT_REGISTER_USAGE)
    if parsed is None:
        return 2
    writer = _writer()
    return _run(lambda: writer.register_project(
        parsed.repo_root,
        parsed.project_id,
        board_scope=parsed.board_scope,
        board_render_path=parsed.board_render_path,
        path=parsed.config_path,
    ))


def config_stamp_project_env(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke config stamp-project-env",
        description=(
            "Stamp every untagged projects entry with the connection env its "
            "project_id belongs to. Defaults to the active env; select another "
            "with the global env flag (e.g. `yoke --env prod config "
            "stamp-project-env`). Already-tagged entries are left untouched."
        ),
    )
    parser.add_argument("--config", dest="config_path", default=None)
    attach_field_note_footer(parser)
    parsed = parse_or_usage_error(parser, args, STAMP_PROJECT_ENV_USAGE)
    if parsed is None:
        return 2
    writer = _writer()
    # env is None here so the writer resolves it from the connection env the
    # invocation selected (global --env / YOKE_ENV, else active_env).
    return _run(lambda: writer.stamp_untagged_project_envs(
        path=parsed.config_path,
    ))


def _run(operation) -> int:
    import sys

    try:
        result = operation()
    except _machine_config_errors() as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


def _connection_set(writer_module, parsed: argparse.Namespace) -> dict:
    credential = _positional_credential_inputs(
        env=parsed.env,
        config_path=parsed.config_path,
        explicit_transport=parsed.transport,
        credential=parsed.credential,
    )
    transport = parsed.transport or _inferred_connection_transport(
        env=parsed.env,
        config_path=parsed.config_path,
        api_url=parsed.api_url,
        token=credential["token"],
        token_file=parsed.token_file,
        token_stdin=parsed.token_stdin,
        dsn=parsed.dsn or credential["dsn"],
        dsn_file=parsed.dsn_file,
        dsn_stdin=parsed.dsn_stdin,
    )
    return writer_module.set_connection(
        parsed.env,
        transport=transport,
        api_url=parsed.api_url,
        token=credential["token"],
        token_file=parsed.token_file,
        token_stdin=parsed.token_stdin,
        dsn=parsed.dsn or credential["dsn"],
        dsn_file=parsed.dsn_file,
        dsn_stdin=parsed.dsn_stdin,
        prod=_prod_flag(parsed),
        path=parsed.config_path,
    )


def _auth_set(writer_module, parsed: argparse.Namespace) -> dict:
    credential = _positional_credential_inputs(
        env=parsed.env,
        config_path=parsed.config_path,
        explicit_transport=None,
        credential=parsed.credential,
    )
    return writer_module.set_credential(
        parsed.env,
        token=credential["token"],
        token_file=parsed.token_file,
        token_stdin=parsed.token_stdin,
        dsn=parsed.dsn or credential["dsn"],
        dsn_file=parsed.dsn_file,
        dsn_stdin=parsed.dsn_stdin,
        path=parsed.config_path,
    )


def _positional_credential_inputs(
    *,
    env: str,
    config_path: str | None,
    explicit_transport: str | None,
    credential: str | None,
) -> dict[str, str | None]:
    if credential is None:
        return {"token": None, "dsn": None}
    transport = explicit_transport or _configured_transport(env, config_path)
    if transport == "local-postgres" or _looks_like_postgres_dsn(credential):
        return {"token": None, "dsn": credential}
    return {"token": credential, "dsn": None}


def _inferred_connection_transport(
    *,
    env: str,
    config_path: str | None,
    api_url: str | None,
    token: str | None,
    token_file: str | None,
    token_stdin: bool,
    dsn: str | None,
    dsn_file: str | None,
    dsn_stdin: bool,
) -> str | None:
    if _configured_transport(env, config_path):
        return None
    if dsn or dsn_file or dsn_stdin:
        return "local-postgres"
    if api_url or token or token_file or token_stdin:
        return "https"
    return None


def _looks_like_postgres_dsn(value: str) -> bool:
    lowered = value.lower()
    return (
        lowered.startswith(("postgres://", "postgresql://"))
        or any(token in lowered for token in ("host=", "dbname=", "sslmode="))
    )


def _prod_flag(parsed: argparse.Namespace) -> bool | None:
    if parsed.prod:
        return True
    if parsed.non_prod:
        return False
    return None


def _configured_transport(env: str, config_path: str | None) -> str | None:
    payload = machine_config.load_config(config_path)
    connections = payload.get("connections")
    if not isinstance(connections, dict):
        return None
    entry = connections.get(env)
    if not isinstance(entry, dict):
        return None
    transport = entry.get("transport")
    return transport if isinstance(transport, str) else None


def _writer():
    return writer


def _machine_config_errors():
    return (writer.MachineConfigWriteError, machine_config.MachineConfigError)


__all__ = [
    "AUTH_SET_USAGE",
    "CONNECTION_SET_USAGE",
    "ENV_USE_USAGE",
    "PROJECT_REGISTER_USAGE",
    "STAMP_PROJECT_ENV_USAGE",
    "auth_set",
    "config_stamp_project_env",
    "connection_set",
    "env_use",
    "project_register",
]
