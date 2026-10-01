"""Serve this checkout's workbench on a spare port, for visual review.

The machine's own `yoke ui` daemon serves the installed build, and taking it
down to look at a branch would interrupt whoever is using it. This starts a
second, independent server from the source tree the caller is standing in, on
a port it picks and prints, and leaves the daemon alone.

    python3 -m runtime.api.tools.serve_workbench_for_review [--port N]

The printed URL carries a token and binds loopback only, exactly as the
daemon's does.
"""

from __future__ import annotations

import argparse
import secrets
import socket

from yoke_core.ui.server import UiServerError, serve_ui
from yoke_core.ui.served_universe_connection import serving_connection


def prepare_review_database() -> None:
    """Converge the selected local review universe before it serves this build."""
    environment, refusal = serving_connection()
    if refusal is not None:
        raise UiServerError(f"review_database_connection_refused: {refusal}")

    from yoke_contracts.control_plane_locality import local_authority_exempt
    from yoke_core.api.server_entrypoint import ensure_core_schema

    try:
        with local_authority_exempt():
            ensure_core_schema()
    except Exception as exc:
        raise UiServerError(
            f"review_database_convergence_failed: {environment or 'local universe'} "
            f"could not converge ({exc}); repair the named schema/history failure "
            "and rerun this review command before capturing evidence"
        ) from exc


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="converge the selected local database without starting the view",
    )
    arguments = parser.parse_args()
    try:
        prepare_review_database()
    except UiServerError as exc:
        parser.exit(1, f"{exc}\n")
    if arguments.prepare_only:
        print("review database: converged", flush=True)
        return
    port = arguments.port or _free_port()
    token = arguments.token or secrets.token_urlsafe(24)
    print(f"review url: http://127.0.0.1:{port}/?token={token}", flush=True)
    serve_ui(port=port, token=token, open_browser=False)


if __name__ == "__main__":
    main()
