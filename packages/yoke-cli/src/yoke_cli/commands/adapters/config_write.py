"""Machine-config writer adapters for the ``yoke`` CLI.

Sibling of :mod:`yoke_cli.commands.adapters.config` (read-side diagnostics).
The env arg is positional on every writer because the CLI's global
``--env`` flag is extracted before adapters parse — a writer flag named
``--env`` would be swallowed by per-command env routing.
"""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.adapters.config_write_project import (
    PROJECT_REGISTER_USAGE as PROJECT_REGISTER_USAGE,
    project_register as project_register,
)
from yoke_cli.commands.adapters.config_write_shared import run as _run
from yoke_cli.config import machine_config
from yoke_cli.config import writer


ENV_USE_USAGE = "yoke env use ENV [--config PATH]"
CONNECTION_SET_USAGE = (
    "yoke connection set ENV [--transport {local-postgres,https}] "
    "[--prod | --non-prod] [--api-url URL] "
    "[CREDENTIAL | --token-file PATH | --token-stdin | --dsn DSN | "
    "--dsn-file PATH | --dsn-stdin] [--config PATH]"
)
CONNECTION_REMOVE_USAGE = "yoke connection remove ENV [--activate ENV] [--config PATH]"
AUTH_SET_USAGE = (
    "yoke auth set ENV [CREDENTIAL | --token-file PATH | --token-stdin | "
    "--dsn DSN | --dsn-file PATH | --dsn-stdin] [--config PATH]"
)
CONFIG_SELECTION_HELP = (
    "Use YOKE_MACHINE_HOME/config.json when YOKE_MACHINE_HOME is set; otherwise "
    "YOKE_MACHINE_CONFIG_FILE selects the config (default ~/.yoke/config.json). "
    "--config selects a path explicitly; writes to a foreign config or outside "
    "an explicit machine home refuse as machine_config_not_owned. "
    "See CLI and config: Machine config."
)
_CREDENTIAL_HELP = "API token or Postgres DSN; the kind is inferred from its shape."


def _add_credential_args(parser: argparse.ArgumentParser) -> None:
    add = parser.add_argument
    add("--token-file", default=None, help="Read the API token from this file.")
    add("--token-stdin", action="store_true", help="Read the API token from stdin.")
    add("--dsn", default=None, help="Postgres DSN for a local-postgres connection.")
    add("--dsn-file", default=None, help="Read the Postgres DSN from this file.")
    add("--dsn-stdin", action="store_true", help="Read the Postgres DSN from stdin.")


def _add_config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Machine config file to write; default: the standard config path.",
    )


def env_use(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        prog="yoke env use",
        description=(
            "Set active_env, the fallback outside registered checkouts. "
            "--env and YOKE_ENV override checkout routing. " + CONFIG_SELECTION_HELP
        ),
    )
    parser.add_argument("env", help="Connection name to make active.")
    _add_config_arg(parser)
    parsed = parse_or_usage_error(parser, args, ENV_USE_USAGE)
    if parsed is None:
        return 2
    writer = _writer()
    return _run(
        lambda: writer.set_active_env(
            parsed.env,
            path=parsed.config_path,
        )
    )


def connection_set(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        prog="yoke connection set",
        description=CONFIG_SELECTION_HELP,
    )
    parser.add_argument("env", help="Connection name to create or change.")
    parser.add_argument("credential", nargs="?", help=_CREDENTIAL_HELP)
    parser.add_argument(
        "--transport",
        choices=["local-postgres", "https"],
        default=None,
        help="How to reach Yoke; default: inferred from the credential given.",
    )
    prod_group = parser.add_mutually_exclusive_group()
    prod_group.add_argument(
        "--prod", action="store_true", help="Mark this connection as production."
    )
    prod_group.add_argument(
        "--non-prod",
        action="store_true",
        help="Mark this connection as not production.",
    )
    parser.add_argument("--api-url", default=None, help="Yoke API URL for https.")
    _add_credential_args(parser)
    _add_config_arg(parser)
    parsed = parse_or_usage_error(parser, args, CONNECTION_SET_USAGE)
    if parsed is None:
        return 2
    if parsed.credential and any(
        (
            parsed.token_file,
            parsed.token_stdin,
            parsed.dsn,
            parsed.dsn_file,
            parsed.dsn_stdin,
        )
    ):
        return usage_error(
            "positional credential is mutually exclusive with credential flags: "
            f"{CONNECTION_SET_USAGE}"
        )
    writer = _writer()
    return _run(lambda: _connection_set(writer, parsed))


def connection_remove(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        prog="yoke connection remove",
        description=(
            "Retire a machine connection alias and its Yoke-owned credential. "
            "Removing the active authority needs --activate to name the "
            "replacement, unless the alias is this machine's only connection, "
            "which simply leaves it unconfigured. Non-owned credential files "
            "are refused. " + CONFIG_SELECTION_HELP
        ),
    )
    parser.add_argument("env", help="Connection name to remove.")
    parser.add_argument(
        "--activate",
        default=None,
        metavar="ENV",
        help="Connection to make active when retiring the active authority.",
    )
    _add_config_arg(parser)
    parsed = parse_or_usage_error(parser, args, CONNECTION_REMOVE_USAGE)
    if parsed is None:
        return 2
    writer = _writer()
    return _run(
        lambda: writer.remove_connection(
            parsed.env,
            activate=parsed.activate,
            path=parsed.config_path,
        )
    )


def auth_set(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        prog="yoke auth set",
        description=CONFIG_SELECTION_HELP,
    )
    parser.add_argument("env", help="Connection name whose credential to set.")
    parser.add_argument("credential", nargs="?", help=_CREDENTIAL_HELP)
    _add_credential_args(parser)
    _add_config_arg(parser)
    parsed = parse_or_usage_error(parser, args, AUTH_SET_USAGE)
    if parsed is None:
        return 2
    if parsed.credential and any(
        (
            parsed.token_file,
            parsed.token_stdin,
            parsed.dsn,
            parsed.dsn_file,
            parsed.dsn_stdin,
        )
    ):
        return usage_error(
            "positional credential is mutually exclusive with credential flags: "
            f"{AUTH_SET_USAGE}"
        )
    writer = _writer()
    return _run(lambda: _auth_set(writer, parsed))


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
    return lowered.startswith(("postgres://", "postgresql://")) or any(
        token in lowered for token in ("host=", "dbname=", "sslmode=")
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


__all__ = [
    "AUTH_SET_USAGE",
    "CONNECTION_SET_USAGE",
    "ENV_USE_USAGE",
    "PROJECT_REGISTER_USAGE",
    "auth_set",
    "connection_set",
    "connection_remove",
    "env_use",
    "project_register",
]
