"""Runtime Postgres DSN resolution from an AWS-managed database secret."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Optional

from yoke_core.domain.yoke_cloud_db_authority import (
    DEFAULT_POSTGRES_PORT,
    PostgresSecret,
    build_libpq_dsn,
)

DB_SECRET_ARN_ENV = "YOKE_DB_SECRET_ARN"
DB_SECRET_REGION_ENV = "YOKE_DB_SECRET_REGION"
DB_SECRET_HOST_ENV = "YOKE_DB_HOST"
DB_SECRET_NAME_ENV = "YOKE_DB_NAME"
DB_SECRET_PORT_ENV = "YOKE_DB_PORT"
DB_SECRET_CACHE_SECONDS_ENV = "YOKE_DB_SECRET_CACHE_SECONDS"
DEFAULT_CACHE_SECONDS = 60.0

SecretLoader = Callable[[str, str], str]


@dataclass(frozen=True)
class ManagedSecretBinding:
    secret_arn: str
    region: str
    host: str
    database: str
    port: Optional[int] = None


_CACHE_KEY: tuple[str, str, str, str, Optional[int]] | None = None
_CACHE_EXPIRES_AT = 0.0
_CACHE_DSN = ""


def resolve_dsn_from_env(
    env: Optional[Mapping[str, str]] = None,
    *,
    loader: Optional[SecretLoader] = None,
    now: Callable[[], float] = time.monotonic,
) -> str:
    """Return a libpq DSN from the managed-secret env binding, or ``""``.

    An absent secret ARN means this resolver is not selected. Once selected,
    the non-secret companion settings are required so the runtime cannot fall
    through to an unrelated local binding with a half-configured cloud env.
    """
    source = os.environ if env is None else env
    secret_arn = source.get(DB_SECRET_ARN_ENV, "").strip()
    if not secret_arn:
        return ""
    binding = ManagedSecretBinding(
        secret_arn=secret_arn,
        region=_required(source, DB_SECRET_REGION_ENV),
        host=_required(source, DB_SECRET_HOST_ENV),
        database=_required(source, DB_SECRET_NAME_ENV),
        port=_optional_port(source.get(DB_SECRET_PORT_ENV, "").strip()),
    )
    cache_seconds = _cache_seconds(source.get(DB_SECRET_CACHE_SECONDS_ENV, ""))
    return resolve_dsn(binding, loader=loader, now=now, cache_seconds=cache_seconds)


def env_binding_selected(env: Optional[Mapping[str, str]] = None) -> bool:
    """Return whether the managed-secret env binding is selected."""
    source = os.environ if env is None else env
    return bool(source.get(DB_SECRET_ARN_ENV, "").strip())


def resolve_dsn(
    binding: ManagedSecretBinding,
    *,
    loader: Optional[SecretLoader] = None,
    now: Callable[[], float] = time.monotonic,
    cache_seconds: float = DEFAULT_CACHE_SECONDS,
) -> str:
    """Resolve *binding* to a libpq DSN, caching briefly per process."""
    global _CACHE_DSN, _CACHE_EXPIRES_AT, _CACHE_KEY

    key = (
        binding.secret_arn,
        binding.region,
        binding.host,
        binding.database,
        binding.port,
    )
    current = now()
    if _CACHE_KEY == key and _CACHE_DSN and current < _CACHE_EXPIRES_AT:
        return _CACHE_DSN

    raw_secret = (loader or _load_secret_string)(
        binding.secret_arn, binding.region
    )
    secret = PostgresSecret.from_json(raw_secret)
    dsn = build_libpq_dsn(
        host=binding.host,
        database=binding.database,
        secret=secret,
        port=binding.port or secret.port or DEFAULT_POSTGRES_PORT,
    )
    _CACHE_KEY = key
    _CACHE_DSN = dsn
    _CACHE_EXPIRES_AT = current + max(cache_seconds, 0.0)
    return dsn


def clear_cache() -> None:
    """Clear the process-local secret-derived DSN cache."""
    global _CACHE_DSN, _CACHE_EXPIRES_AT, _CACHE_KEY
    _CACHE_KEY = None
    _CACHE_DSN = ""
    _CACHE_EXPIRES_AT = 0.0


def _load_secret_string(secret_arn: str, region: str) -> str:
    import boto3

    client = boto3.client("secretsmanager", region_name=region)
    payload = client.get_secret_value(SecretId=secret_arn)
    secret = payload.get("SecretString")
    if not isinstance(secret, str) or not secret:
        raise RuntimeError("database secret payload did not include SecretString")
    return secret


def _required(source: Mapping[str, str], key: str) -> str:
    value = source.get(key, "").strip()
    if not value:
        raise RuntimeError(f"{key} must be set when {DB_SECRET_ARN_ENV} is set")
    return value


def _optional_port(raw: str) -> Optional[int]:
    if not raw:
        return None
    try:
        port = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{DB_SECRET_PORT_ENV} must be an integer") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError(f"{DB_SECRET_PORT_ENV} must be between 1 and 65535")
    return port


def _cache_seconds(raw: str) -> float:
    if not raw:
        return DEFAULT_CACHE_SECONDS
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"{DB_SECRET_CACHE_SECONDS_ENV} must be numeric"
        ) from exc
    if value < 0:
        raise RuntimeError(
            f"{DB_SECRET_CACHE_SECONDS_ENV} must be non-negative"
        )
    return value


__all__ = [
    "DB_SECRET_ARN_ENV",
    "DB_SECRET_CACHE_SECONDS_ENV",
    "DB_SECRET_HOST_ENV",
    "DB_SECRET_NAME_ENV",
    "DB_SECRET_PORT_ENV",
    "DB_SECRET_REGION_ENV",
    "ManagedSecretBinding",
    "clear_cache",
    "env_binding_selected",
    "resolve_dsn",
    "resolve_dsn_from_env",
]
