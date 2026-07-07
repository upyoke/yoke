"""Tests for runtime DB DSN resolution from managed cloud secrets."""

from __future__ import annotations

import pytest

from yoke_core.domain import cloud_db_secret_dsn as resolver


def setup_function() -> None:
    resolver.clear_cache()


def test_resolves_libpq_dsn_from_managed_secret_env() -> None:
    calls: list[tuple[str, str]] = []

    def loader(secret_arn: str, region: str) -> str:
        calls.append((secret_arn, region))
        return '{"username":"yoke_admin","password":"p a s s","port":5433}'

    dsn = resolver.resolve_dsn_from_env(
        {
            resolver.DB_SECRET_ARN_ENV: "arn:aws:secretsmanager:secret",
            resolver.DB_SECRET_REGION_ENV: "us-east-1",
            resolver.DB_SECRET_HOST_ENV: "db.internal",
            resolver.DB_SECRET_NAME_ENV: "yoke_prod",
            resolver.DB_SECRET_CACHE_SECONDS_ENV: "60",
        },
        loader=loader,
        now=lambda: 10.0,
    )

    assert "host=db.internal" in dsn
    assert "port=5433" in dsn
    assert "user=yoke_admin" in dsn
    assert "password='p a s s'" in dsn
    assert "dbname=yoke_prod" in dsn
    assert calls == [("arn:aws:secretsmanager:secret", "us-east-1")]


def test_secret_derived_dsn_is_cached_briefly() -> None:
    calls = 0

    def loader(secret_arn: str, region: str) -> str:  # noqa: ARG001
        nonlocal calls
        calls += 1
        return f'{{"username":"u","password":"p{calls}"}}'

    env = {
        resolver.DB_SECRET_ARN_ENV: "arn",
        resolver.DB_SECRET_REGION_ENV: "us-east-1",
        resolver.DB_SECRET_HOST_ENV: "db.internal",
        resolver.DB_SECRET_NAME_ENV: "yoke_prod",
        resolver.DB_SECRET_CACHE_SECONDS_ENV: "5",
    }

    first = resolver.resolve_dsn_from_env(env, loader=loader, now=lambda: 1.0)
    second = resolver.resolve_dsn_from_env(env, loader=loader, now=lambda: 2.0)
    third = resolver.resolve_dsn_from_env(env, loader=loader, now=lambda: 7.0)

    assert "password=p1" in first
    assert second == first
    assert "password=p2" in third
    assert calls == 2


def test_secret_arn_requires_complete_non_secret_binding() -> None:
    with pytest.raises(RuntimeError) as exc:
        resolver.resolve_dsn_from_env({resolver.DB_SECRET_ARN_ENV: "arn"})

    assert resolver.DB_SECRET_REGION_ENV in str(exc.value)
