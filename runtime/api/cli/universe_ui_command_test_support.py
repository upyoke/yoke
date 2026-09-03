"""Shared stubs for the ``yoke ui`` command-surface tests.

The engine is stubbed at the dynamic-import seam
(``universe_ui_connection.ui_server``) so the client half can be pinned
without a universe; the daemon reports are hand-built so the command
tests observe the surface rather than the process lifecycle, which
``test_yoke_universe_ui_daemon.py`` covers against a real child.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict

STUB_TOKEN = "stub-token"
STUB_PORT = 9999


def stub_server(record: Dict[str, Any], *, busy_port: bool = False):
    def resolve_ui_host(requested=None):
        host = requested or "127.0.0.1"
        if host not in {"127.0.0.1", "localhost"}:
            raise RuntimeError("host must be loopback-only")
        return host

    def resolve_ui_port(requested=None, *, host="127.0.0.1"):
        if busy_port:
            raise RuntimeError(
                f"port {STUB_PORT} is already in use; pick another with --port"
            )
        return int(requested or STUB_PORT)

    def serve_ui(*, host, port, token, open_browser):
        record["served"] = {
            "host": host,
            "port": port,
            "token": token,
            "open_browser": open_browser,
        }

    return SimpleNamespace(
        resolve_ui_host=resolve_ui_host,
        resolve_ui_port=resolve_ui_port,
        mint_session_token=lambda: STUB_TOKEN,
        private_url=lambda port, token, *, host="127.0.0.1": (
            f"http://{host}:{port}/?token={token}"
        ),
        serve_ui=serve_ui,
    )


def running_report(port: int = STUB_PORT) -> Dict[str, Any]:
    return {
        "running": True,
        "pid": 4242,
        "host": "127.0.0.1",
        "port": port,
        "env": "local",
        "started_at": "2026-09-03T01:00:00Z",
        "serving": True,
        "supervised_by_launchd": False,
        "state_dir": "/machine/ui",
        "private_url": f"http://127.0.0.1:{port}/?token={STUB_TOKEN}",
    }


def write_local_connection(env: str = "local", *, prod: bool = False) -> None:
    from yoke_cli.config import writer

    writer.set_connection(
        env, transport="local-postgres",
        dsn="host=/sock user=yoke dbname=yoke", prod=prod,
    )
    writer.set_active_env(env)


__all__ = [
    "STUB_PORT",
    "STUB_TOKEN",
    "running_report",
    "stub_server",
    "write_local_connection",
]
