"""Container-facing uvicorn entrypoint for the Yoke API service.

Boot behavior branches on universe born-ness against the server's resolved
DSN. A born database boots idempotently (core schema ensure + permission
catalog reseed). An empty database is birthed in full before the first
request is served — control-plane bootstrap, org identity card, admin actor
with the org ``admin`` role, and a one-time admin token printed to stdout —
and any birth failure aborts the boot: the server never serves a half-born
universe. Because the born-ness sentinel (the org identity card) commits
early in the birth while the admin token mints at the very end, a boot that
died in between leaves a database that reads born with no credential; the
next boot detects that shape and re-enters the birth instead of serving.
"""

from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence


_log = logging.getLogger("yoke.api.startup")

DEFAULT_APP = "yoke_core.api.main:app"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_LOG_LEVEL = "info"
DEFAULT_PORT = 8765
DEFAULT_WORKERS = 1

#: Env var naming the org identity card on first boot. Unset keeps the
#: neutral seeded default name.
ORG_NAME_ENV = "YOKE_ORG_NAME"

#: Marker line inside the one-time admin-token block. Tests key on it and
#: operators can grep captured boot output for it.
FIRST_BOOT_TOKEN_MARKER = "FIRST-BOOT ADMIN TOKEN"


@dataclass(frozen=True)
class ServerSettings:
    app: str
    host: str
    log_level: str
    port: int
    workers: int


def _parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"port must be an integer, got {value!r}"
        ) from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(
            f"port must be between 1 and 65535, got {value!r}"
        )
    return port


def _parse_workers(value: str) -> int:
    try:
        workers = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"workers must be an integer, got {value!r}"
        ) from exc
    if workers < 1:
        raise argparse.ArgumentTypeError(f"workers must be at least 1, got {value!r}")
    return workers


def build_parser(env: Optional[Mapping[str, str]] = None) -> argparse.ArgumentParser:
    source = os.environ if env is None else env
    parser = argparse.ArgumentParser(description="Run the Yoke API service.")
    parser.add_argument(
        "--app",
        default=source.get("YOKE_API_APP", DEFAULT_APP),
        help="ASGI application import string.",
    )
    parser.add_argument(
        "--host",
        default=source.get("YOKE_API_HOST", DEFAULT_HOST),
        help="Host interface to bind.",
    )
    parser.add_argument(
        "--port",
        default=source.get("YOKE_API_PORT", str(DEFAULT_PORT)),
        type=_parse_port,
        help="TCP port to bind.",
    )
    parser.add_argument(
        "--log-level",
        default=source.get("YOKE_API_LOG_LEVEL", DEFAULT_LOG_LEVEL),
        help="Uvicorn log level.",
    )
    parser.add_argument(
        "--workers",
        default=source.get("YOKE_API_WORKERS", str(DEFAULT_WORKERS)),
        type=_parse_workers,
        help="Uvicorn worker count.",
    )
    return parser


def resolve_settings(
    argv: Optional[Sequence[str]] = None,
    env: Optional[Mapping[str, str]] = None,
) -> ServerSettings:
    parsed = build_parser(env=env).parse_args(argv)
    return ServerSettings(
        app=parsed.app,
        host=parsed.host,
        log_level=parsed.log_level,
        port=parsed.port,
        workers=parsed.workers,
    )


def ensure_permission_catalog(*, fail_soft: bool = True) -> bool:
    """Reseed the role/permission catalog on boot (idempotent, fail-soft).

    Closes the deploy-time drift where a new code-defined permission (e.g.
    ``db.read.raw``) stayed absent on a long-lived DB until someone manually
    re-seeded: every container boot now upserts the catalog so the database
    matches the deployed code. The seed is idempotent (``ON CONFLICT``) and runs
    against the canonical DB resolved by ``db_helpers``. A failure must not
    brick the container — the prior catalog stays in place and the next boot
    retries — so the default boot policy logs errors instead of raising.
    Explicit source-dev convergence passes ``fail_soft=False`` so it cannot
    report success when the catalog did not converge.
    """
    try:
        from yoke_core.domain import db_helpers
        from yoke_core.domain.actor_permissions import seed_roles_and_permissions
        from yoke_core.domain.auth_schema import create_auth_tables

        with db_helpers.connect() as conn:
            create_auth_tables(conn)
            seed_roles_and_permissions(conn)
        _log.info("permission catalog reseeded on boot")
        return True
    except Exception:  # noqa: BLE001 - policy chooses boot vs operator behavior
        if not fail_soft:
            raise
        _log.exception("permission-catalog reseed on boot failed; continuing")
        return False


def ensure_core_schema() -> None:
    """Converge the idempotent core schema before the API starts serving.

    A container with a long-lived DB must not report healthy while deployed
    code requires tables OR columns the DB has not yet created. This runs the
    full idempotent schema convergence (tables, indexes, additive columns) so a
    deploy propagates every additive schema change to an already-born universe —
    the boot after a deploy is the only schema-reconciliation point on the prod
    path. It is strictly non-destructive: the birth-only drops and data
    backfills stay in :func:`yoke_core.domain.schema_init.cmd_init`. Fail-hard:
    if convergence cannot complete, the API must not start.
    """
    from yoke_core.domain import db_helpers
    from yoke_core.domain.schema_init import converge_core_schema

    with db_helpers.connect() as conn:
        converge_core_schema(conn)
    _log.info("core schema converged on boot")


def universe_is_born() -> bool:
    """Probe whether the server's resolved DSN already carries a universe."""
    from yoke_core.domain import db_backend, environment_bootstrap

    return environment_bootstrap.universe_is_born(db_backend.resolve_pg_dsn())


def admin_credential_exists() -> bool:
    """Probe whether the universe ever minted an API credential.

    The born-ness sentinel (the org identity card) commits early in the
    birth's init chain while the first-boot admin token mints at the very
    end, so a boot that died between the two leaves a database that reads
    born although the operator's only credential never existed. Any
    ``api_tokens`` row is the completeness signature: a finished server
    birth always mints the initial admin token, and token rows survive
    revocation (status flips; rows are never deleted). A missing table
    reads as "no credential". The shared born-ness probe cannot carry this
    check because embedded local universes are legitimately token-less;
    only the served API requires a bearer credential to be usable.
    """
    import psycopg

    from yoke_core.domain import db_backend

    conn = db_backend.connect_psycopg(db_backend.resolve_pg_dsn())
    try:
        with conn:
            row = conn.execute("SELECT COUNT(*) FROM api_tokens").fetchone()
            return bool(row and int(row[0]) >= 1)
    except psycopg.errors.UndefinedTable:
        return False
    finally:
        conn.close()


def birth_universe() -> None:
    """Bootstrap an empty server database into a complete universe (fail-hard).

    Runs the full environment bootstrap against the server's resolved DSN,
    ensures the org identity card (named by :data:`ORG_NAME_ENV` when set),
    grants the admin human actor the org ``admin`` role, and prints the
    one-time admin token to stdout. Any failure propagates — the server
    must never serve a half-born universe. A completed birth never
    re-enters this path; an interrupted one (born-ness committed, token
    never minted) re-enters it on every boot until it completes, so the
    token is still minted and printed exactly once in the universe's
    lifetime.
    """
    from yoke_core.domain import db_helpers, org_schema
    from yoke_core.domain.actors import LOCAL_HUMAN_LABEL_ENV
    from yoke_core.domain.api_tokens import (
        DEFAULT_ADMIN_ACTOR_LABEL,
        bootstrap_admin_token,
    )
    from yoke_core.domain.environment_bootstrap import run_bootstrap

    # The init chain invokes its modules with no parameters, so the admin
    # label rides the same pinned-env idiom the local-universe birth uses
    # for the OS login. This makes the canonical human actor the chain
    # seeds THE admin actor the token binds to — one human row, no
    # founder-fallback label on a self-hosted universe.
    prior_label = os.environ.get(LOCAL_HUMAN_LABEL_ENV)
    os.environ[LOCAL_HUMAN_LABEL_ENV] = DEFAULT_ADMIN_ACTOR_LABEL
    try:
        run_bootstrap(emit=_log.info)
    finally:
        if prior_label is None:
            os.environ.pop(LOCAL_HUMAN_LABEL_ENV, None)
        else:
            os.environ[LOCAL_HUMAN_LABEL_ENV] = prior_label
    org_name = (os.environ.get(ORG_NAME_ENV) or "").strip() or None
    with db_helpers.connect() as conn:
        org = org_schema.ensure_org_identity_card(conn, org_name)
        created = bootstrap_admin_token(conn)
    _log.info("universe born: org %r", org["name"])
    _print_admin_token_once(created.raw_token)


def _print_admin_token_once(raw_token: str) -> None:
    """Print the one-time admin-token block to stdout.

    Sanctioned secret print: this is the only copy of the raw token in
    existence (the DB stores a hash), and the credential probe guarantees
    no boot after a completed birth re-enters the printing path.
    """
    border = "=" * 64
    print(
        "\n".join(
            (
                border,
                f"  {FIRST_BOOT_TOKEN_MARKER} — shown once, never stored, never reprinted",
                "",
                f"      {raw_token}",
                "",
                "  Save it now, then connect a client to this server with:",
                "      yoke connect <server-url>",
                border,
            )
        ),
        flush=True,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    settings = resolve_settings(argv)
    if not universe_is_born():
        _log.info("empty database detected: bootstrapping a fresh universe")
        birth_universe()
    elif not admin_credential_exists():
        # A prior birth died after the born-ness sentinel committed but
        # before the end-of-birth token mint. Serving now would strand a
        # permanently credential-less universe; re-enter the idempotent
        # birth so the one-time admin token still gets minted and printed.
        _log.warning(
            "born universe carries no API credential: "
            "completing an interrupted birth before serving"
        )
        birth_universe()
    else:
        ensure_core_schema()
        # Reseed the permission catalog before serving so a deploy of new
        # code that adds permissions propagates to the DB without a manual
        # seed step.
        ensure_permission_catalog()
    import uvicorn

    # log_config=None: do not let uvicorn install its plain-text dictConfig.
    # The app already installs a JSON stdout handler on the root logger
    # (configure_observability), so uvicorn's own loggers propagate to it
    # and CloudWatch receives one consistent JSON stream.
    # access_log=False: the bearer-token middleware emits a structured
    # HttpRequestCompleted log per request, so uvicorn's plain-text access
    # lines would be redundant noise mixed into the JSON stream.
    uvicorn.run(
        settings.app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        workers=settings.workers,
        access_log=False,
        log_config=None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
