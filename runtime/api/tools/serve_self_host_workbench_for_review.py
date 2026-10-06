"""Serve this checkout as a self-hosted Yoke server, signed in, for review.

A self-hosted server serves the workbench itself, behind browser sign-in.
This starts the Yoke server app from the source tree the caller is standing
in, on a loopback port it picks and prints, against the selected local
review universe, with browser sign-in pointed at an in-process OIDC
provider that approves without a login screen. Opening the printed sign-in
URL lands a browser on the workbench as the universe's local operator
actor, so a Browser case can capture the signed-in workbench and prove the
commit it serves at ``/served-build``.

    YOKE_ENV=render-proof python3 -m \\
        runtime.api.tools.serve_self_host_workbench_for_review [--port N]

Before merge, run it through ``yoke dev run --`` so the lane's source is what
serves. Commit first: an uncommitted tree publishes ``<sha>-dirty``.
"""

from __future__ import annotations

import argparse
import os
import socket
import tempfile
from pathlib import Path

from runtime.api.oidc_provider_test_helpers import StubOidcProvider
from runtime.api.tools.serve_workbench_for_review import prepare_review_database
from yoke_core.api.http_auth import OIDC_START_PATH
from yoke_core.ui.server import UiServerError

_REVIEW_SUBJECT = "self-host-review-operator"
_REVIEW_EMAIL = "review-operator@self-host-review.invalid"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _link_review_identity(issuer: str) -> int:
    """Link the provider's review identity to the local operator actor."""
    from yoke_core.domain import db_helpers
    from yoke_core.domain.external_identities import link_external_identity
    from yoke_core.ui.local_operator_actor import resolve_local_operator_actor

    actor_id = resolve_local_operator_actor()
    if actor_id is None:
        raise UiServerError(
            "review_operator_unresolved: the selected universe has no single "
            "human operator actor to sign in as; select a review universe "
            "with one (YOKE_ENV=render-proof) and rerun"
        )
    with db_helpers.connect() as conn:
        link_external_identity(
            conn,
            actor_id=int(actor_id),
            issuer=issuer,
            subject=_REVIEW_SUBJECT,
            email=_REVIEW_EMAIL,
        )
        conn.commit()
    return int(actor_id)


def _configure_sign_in(provider: StubOidcProvider, base_url: str) -> None:
    secret_file = Path(tempfile.mkdtemp()) / "oidc-client-secret"
    secret_file.write_text(provider.client_secret + "\n", encoding="utf-8")
    secret_file.chmod(0o600)
    os.environ["YOKE_OIDC_ISSUER"] = provider.issuer
    os.environ["YOKE_OIDC_CLIENT_ID"] = provider.client_id
    os.environ["YOKE_OIDC_CLIENT_SECRET_FILE"] = str(secret_file)
    os.environ["YOKE_OIDC_REDIRECT_URL"] = base_url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=None)
    arguments = parser.parse_args()
    try:
        prepare_review_database()
    except UiServerError as exc:
        parser.exit(1, f"{exc}\n")
    port = arguments.port or _free_port()
    base_url = f"http://127.0.0.1:{port}"
    provider = StubOidcProvider(
        auto_approve_claims={
            "sub": _REVIEW_SUBJECT,
            "email": _REVIEW_EMAIL,
            "email_verified": True,
        }
    )
    try:
        actor_id = _link_review_identity(provider.issuer)
    except UiServerError as exc:
        provider.close()
        parser.exit(1, f"{exc}\n")
    _configure_sign_in(provider, base_url)

    import uvicorn

    import yoke_core.api.main  # noqa: F401  (import-order anchor)
    from yoke_core.api.app_factory import create_app

    print(f"server url: {base_url}/", flush=True)
    print(f"sign-in url: {base_url}{OIDC_START_PATH}", flush=True)
    print(f"signs in as actor: {actor_id}", flush=True)
    try:
        uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")
    finally:
        provider.close()


if __name__ == "__main__":
    main()
