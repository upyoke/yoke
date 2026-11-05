# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

from types import SimpleNamespace

from typing import Any

import pytest

from psycopg import conninfo

from yoke_core.tools import fleet_rehearsal_receipt_write as receipt_write

from yoke_core.tools import migration_fleet_selection

from yoke_core.tools import preflight_fleet_migrations as preflight

from runtime.api.tools import report_yoke_tenant_migration_state as reporter

from runtime.api.tools.adopt_migration_content_identity_test_support import (
    _argv,
    _artifact,
    _legacy_connection,
    _mock_github_attestations,
)

from yoke_core.domain import connected_env_readiness as readiness

from yoke_core.domain import (
    local_universe,
    local_universe_autostart,
    migration_fleet_preflight,
)

from yoke_core.tools import adopt_migration_content_identity as adopter

from yoke_core.tools import yoke_migration_fleet as fleet_selector

SELECTED_DSN = "host=selected.example user=admin dbname=postgres"


def _declare_admin(monkeypatch: pytest.MonkeyPatch, mapping: dict[str, str]) -> None:
    def read(*, project: str, environment: str) -> tuple[str, str]:
        del project
        admin = mapping.get(environment, "")
        if not admin:
            return (
                "",
                f"environment {environment!r} does not declare release.admin_connection",
            )
        return admin, ""

    monkeypatch.setattr(
        "yoke_core.domain.migration_preflight_receipt_store.read_declared_admin_connection",
        read,
    )


def _select_yoke_fleet(monkeypatch: pytest.MonkeyPatch) -> None:
    target = migration_fleet_selection.FleetTarget(
        project="yoke",
        model_name="primary",
        plan=SimpleNamespace(history=("0001_existing",)),
        databases=lambda _dsn_for: ["yoke_alpha"],
        schema_shape_digest=lambda: "digest-for-test",
    )
    monkeypatch.setattr(
        migration_fleet_selection, "resolve", lambda *_args, **_kw: (target, "")
    )


def _authority(environment: str) -> SimpleNamespace:
    return SimpleNamespace(environment=environment, dsn=SELECTED_DSN)
