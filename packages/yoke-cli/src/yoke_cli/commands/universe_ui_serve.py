"""``yoke ui serve-process`` — the foreground server the daemon supervises.

This is the child entrypoint, not an operator command: ``yoke ui up``
starts it detached (through a launchd user agent on macOS, a detached
child elsewhere) and ``yoke ui down`` stops it. Running it directly
serves the view in the foreground and ties it to the terminal, which is
exactly what the daemon exists to avoid — so operators want
``yoke ui up``.

The serving process is the one that converges the universe schema,
re-checks that the connection may be served, reads the machine's stable
session token, and publishes the daemon record naming its own pid. That
keeps status and stop reading one shape whether launchd or a parent
process brought the view up.
"""

from __future__ import annotations

import argparse
import sys
from typing import List

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.commands import universe_ui_connection as connection
from yoke_cli.commands.universe_ui_connection import UniverseUiError
from yoke_cli.config import universe_ui_daemon as daemon
from yoke_cli.config.universe_ui_daemon_state import (
    UiDaemonError,
    stable_session_token,
)

UI_SERVE_PROCESS_USAGE = "yoke ui serve-process [--host HOST] [--port PORT]"


def ui_serve_process(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ui serve-process",
        description=(
            "Serve the machine-local universe view in the foreground. "
            "This is the process `yoke ui up` supervises; run `yoke ui "
            "up` instead unless you are deliberately tying the view to "
            "this terminal."
        ),
    )
    parser.add_argument(
        "--host", default=None,
        help="Loopback host to bind (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help="TCP port to bind (default: the server's canonical port).",
    )
    parsed = parse_or_usage_error(parser, args, UI_SERVE_PROCESS_USAGE)
    if parsed is None:
        return 2

    env_name, refusal = connection.servable_connection()
    if refusal is not None:
        print(f"error: {refusal}", file=sys.stderr)
        return 1

    try:
        connection.converge_universe_schema()
    except UniverseUiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            f"error: the local universe's schema could not converge: {exc}",
            file=sys.stderr,
        )
        return 1

    try:
        server = connection.ui_server()
        host = server.resolve_ui_host(parsed.host)
        port = server.resolve_ui_port(parsed.port, host=host)
        token = stable_session_token()
    except (UniverseUiError, UiDaemonError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    daemon.publish_serving_identity(host=host, port=port, env=env_name)
    try:
        server.serve_ui(
            host=host, port=port, token=token, open_browser=False,
        )
    except KeyboardInterrupt:
        return 0
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        daemon.retract_serving_identity()
    return 0


__all__ = ["UI_SERVE_PROCESS_USAGE", "ui_serve_process"]
