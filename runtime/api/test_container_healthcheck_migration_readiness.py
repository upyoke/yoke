"""The container healthcheck refuses explicit unsafe migration states."""

from __future__ import annotations

import json

import pytest

from yoke_core.api import container_healthcheck


class _Response:
    status = 200

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


@pytest.mark.parametrize(
    ("migration_fields", "expected", "detail"),
    [
        (
            {
                "migrations_current": False,
                "pending_migrations": ["0004_backfill_serving_floors"],
            },
            "migrations_current=true",
            "0004_backfill_serving_floors",
        ),
        (
            {
                "migrations_current": True,
                "can_serve_this_database": False,
                "stranded_by_migrations": ["0001 requires launch.181"],
            },
            "can_serve_this_database=false",
            "0001 requires launch.181",
        ),
    ],
)
def test_container_healthcheck_rejects_migration_refusal(
    migration_fields: dict[str, object],
    expected: str,
    detail: str,
) -> None:
    payload = {"status": "ok", "schema_ready": True, **migration_fields}

    def opener(url: str, timeout: float) -> _Response:  # noqa: ARG001
        return _Response(payload)

    with pytest.raises(RuntimeError) as exc:
        container_healthcheck.check_health(
            container_healthcheck.resolve_settings(env={}),
            opener=opener,
        )

    assert expected in str(exc.value)
    assert detail in str(exc.value)
