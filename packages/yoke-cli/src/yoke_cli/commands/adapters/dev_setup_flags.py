"""Argument validation and connector option shapes for source-dev setup."""

from __future__ import annotations
import argparse
from typing import Any


class DevSetupAdapterError(RuntimeError):
    """Adapter argument combinations are incomplete."""


def _checkout_and_positional_dsn(
    parsed: argparse.Namespace,
) -> tuple[str | None, str | None]:
    first = parsed.checkout_or_dsn
    second = parsed.dsn_value
    if second is not None:
        return first, second
    if first is not None and _looks_like_postgres_dsn(first):
        return None, first
    return first, None


def _looks_like_postgres_dsn(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(("postgres://", "postgresql://")) or any(
        token in lowered for token in ("host=", "dbname=", "sslmode=")
    )


def _add_secret_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dsn", dest="dsn", default=None)
    parser.add_argument("--dsn-file", dest="dsn_file", default=None)
    parser.add_argument("--dsn-stdin", dest="dsn_stdin", action="store_true")


def _add_tunnel_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tunnel-bastion", default=None)
    parser.add_argument("--tunnel-identity-file", default=None)
    parser.add_argument("--tunnel-remote-host", default=None)
    parser.add_argument("--tunnel-remote-port", type=int, default=None)


def _add_authority_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--authority-kind", default=None)
    parser.add_argument("--authority-infra-dir", default=None)
    parser.add_argument("--authority-stack", default=None)
    parser.add_argument("--authority-region", default=None)
    parser.add_argument("--authority-database-name", default=None)


def _postgres(parsed: argparse.Namespace) -> dict[str, Any]:
    postgres = {
        key: value
        for key, value in (
            ("host", parsed.postgres_host),
            ("port", parsed.postgres_port),
        )
        if value is not None
    }
    tunnel = _tunnel(parsed)
    if tunnel:
        postgres["tunnel"] = tunnel
    return postgres


def _tunnel(parsed: argparse.Namespace) -> dict[str, Any]:
    values = {
        "bastion": parsed.tunnel_bastion,
        "identity_file": parsed.tunnel_identity_file,
        "remote_host": parsed.tunnel_remote_host,
        "remote_port": parsed.tunnel_remote_port,
    }
    if not any(value is not None for value in values.values()):
        return {}
    missing = [key for key, value in values.items() if value is None]
    if missing:
        raise DevSetupAdapterError(
            "--tunnel-* options must be supplied together; missing "
            + ", ".join(missing)
        )
    values["kind"] = "ssh"
    return values


def _authority(parsed: argparse.Namespace) -> dict[str, Any]:
    values = {
        "kind": parsed.authority_kind,
        "infra_dir": parsed.authority_infra_dir,
        "stack": parsed.authority_stack,
        "region": parsed.authority_region,
        "database_name": parsed.authority_database_name,
    }
    if not any(value for value in values.values()):
        return {}
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise DevSetupAdapterError(
            "--authority-* options must be supplied together; missing "
            + ", ".join(missing)
        )
    return {
        "kind": values["kind"],
        "infra_dir": values["infra_dir"],
        "location": {
            "stack": values["stack"],
            "region": values["region"],
            "database_name": values["database_name"],
        },
    }
