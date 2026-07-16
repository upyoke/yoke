"""Tool-shaped ``yoke ui`` — the door to the machine-local universe view.

Serves the token-gated, read-only web view of the universe this machine
holds. Transport-keyed like every other local-universe surface, as an
allowlist: only a non-prod local-postgres connection starts the UI server
in-process (the engine dispatches reads through the same in-process
product path the CLI uses). Every other mode refuses in mode language —
https because hosted and self-hosted web surfaces arrive with the
platform, prod-flagged Postgres because direct prod authority stays
operator-only, and anything unrecognized fails closed.

The engine import is dynamic on purpose: the client packages hold no
static import authority over the engine, and local mode is the one lane
where a product install *runs* it (same rule as ``yoke init --local``).

The tokened URL printed here is the user's door — terminal-only output,
never written into event streams or logs. ``--json`` carries it under
``private_url`` so the secrecy is obvious to tooling.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from typing import Callable, Dict, List, Optional, Tuple

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.config import machine_config
from yoke_contracts.machine_config.schema import (
    MachineConfigContractError,
    POSTGRES_TRANSPORTS,
    TRANSPORT_HTTPS,
    connection_is_prod,
)

AdapterFn = Callable[[List[str]], int]

UI_USAGE = "yoke ui [--host HOST] [--port PORT] [--no-browser] [--json]"

TOOL_SHAPED_USAGE: Dict[str, str] = {"yoke ui": UI_USAGE}

_ENGINE_MISSING_MESSAGE = (
    "the yoke-core engine package is not importable on this machine; "
    "reinstall Yoke (the engine ships in every product install)"
)


class UniverseUiError(RuntimeError):
    """The UI server could not be started for the active connection."""


def _ui_server():
    try:
        return importlib.import_module("yoke_core.ui.server")
    except ModuleNotFoundError as exc:
        raise UniverseUiError(_ENGINE_MISSING_MESSAGE) from exc


def _converge_universe_schema() -> None:
    """Converge the local universe's schema before serving it.

    The UI server is a server booting against this universe, and every
    boot is a schema-reconciliation point: a universe born before a
    newer additive table would otherwise answer reads with undefined-
    relation errors until some other boot converges it. Same fail-hard
    contract as the API server — a UI over a half-converged universe
    would lie about what exists.
    """
    try:
        entrypoint = importlib.import_module(
            "yoke_core.api.server_entrypoint",
        )
    except ModuleNotFoundError as exc:
        raise UniverseUiError(_ENGINE_MISSING_MESSAGE) from exc
    entrypoint.ensure_core_schema()


def _refuse_for_connection_mode() -> Optional[str]:
    """Refusal text when the active connection cannot serve a local UI.

    Allowlist, not denylist: only a non-prod local-postgres connection is
    served. Every other mode — https, prod-flagged Postgres, or any
    transport this adapter does not recognize — refuses in mode language,
    so new connection modes fail closed until deliberately admitted.
    """
    config_file = machine_config.config_path()
    try:
        connection = machine_config.active_connection()
    except (machine_config.MachineConfigError, MachineConfigContractError) as exc:
        if config_file.is_file():
            return (
                f"the machine config at {config_file} cannot be used: "
                f"{exc}; repair it (or start over from "
                "`yoke config example`) before `yoke ui` can serve"
            )
        return (
            "no active connection is configured on this machine; "
            "`yoke init --local` creates a local universe to view"
        )
    env_label = str(connection.get("env") or "<env>")
    transport = str(connection.get("transport") or "").strip()
    if transport in POSTGRES_TRANSPORTS and not connection_is_prod(connection):
        return None
    if transport == TRANSPORT_HTTPS:
        return (
            f"the active connection {env_label!r} is https-transport "
            "(hosted/self-host mode): `yoke ui` serves the machine-local "
            "universe only, and the hosted/self-host web surfaces arrive "
            "with the platform. To view a machine-local universe, switch "
            "to its env (`yoke env use local`) or create one "
            "(`yoke init --local`)."
        )
    if transport in POSTGRES_TRANSPORTS:
        return (
            f"the active connection {env_label!r} is a prod-flagged "
            "Postgres connection: direct prod authority is operator-only, "
            "so `yoke ui` refuses to serve it."
        )
    return (
        f"the active connection {env_label!r} (transport "
        f"{transport or '<unset>'!r}) is not a mode `yoke ui` recognizes: "
        "only a non-prod local-postgres connection serves the "
        "machine-local universe. Switch to one (`yoke env use <env>`) or "
        "create one (`yoke init --local`)."
    )


def ui(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ui",
        description=(
            "Serve the read-only web view of the machine-local universe. "
            "Binds loopback only, mints one random session token per run, "
            "and prints the tokened URL — that URL is the door; treat it "
            "like a password. Requires a non-prod local-postgres "
            "connection (`yoke init --local`)."
        ),
    )
    parser.add_argument(
        "--host", default=None,
        help=(
            "Loopback host for the UI server (default: 127.0.0.1; "
            "remote-facing hosts are refused)."
        ),
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help=(
            "TCP port for the UI server (default: the server's canonical "
            "port; refused with guidance when already in use)."
        ),
    )
    parser.add_argument(
        "--no-browser", dest="no_browser", action="store_true",
        help="Do not open the default browser on the tokened URL.",
    )
    parser.add_argument(
        "--json", dest="json_mode", action="store_true",
        help=(
            "Print a JSON line naming port and private_url (the tokened "
            "URL — private by construction) before serving."
        ),
    )
    parsed = parse_or_usage_error(parser, args, UI_USAGE)
    if parsed is None:
        return 2

    refusal = _refuse_for_connection_mode()
    if refusal is not None:
        print(f"error: {refusal}", file=sys.stderr)
        return 1

    try:
        _converge_universe_schema()
        server = _ui_server()
        host = server.resolve_ui_host(parsed.host)
        port = server.resolve_ui_port(parsed.port, host=host)
    except (UniverseUiError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            f"error: the local universe's schema could not converge: {exc}",
            file=sys.stderr,
        )
        return 1
    token = server.mint_session_token()
    url = server.private_url(port, token, host=host)

    if parsed.json_mode:
        print(json.dumps({
            "ok": True,
            "host": host,
            "port": port,
            "private_url": url,
            "browser_opened": not parsed.no_browser,
        }, sort_keys=True), flush=True)
    else:
        print("yoke ui: serving the local universe (read-only) at:")
        print(f"  {url}")
        print("This URL is the door — treat it like a password.")
        print("Press Ctrl-C to stop.", flush=True)

    try:
        server.serve_ui(
            host=host,
            port=port,
            token=token,
            open_browser=not parsed.no_browser,
        )
    except KeyboardInterrupt:
        print("yoke ui: stopped", file=sys.stderr)
        return 0
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("ui",): ui,
}


__all__ = [
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "UI_USAGE",
    "UniverseUiError",
    "ui",
]
