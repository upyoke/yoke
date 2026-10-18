# ruff: noqa: F811
"""``/v1/health`` schema-readiness payload tests.

Sibling of ``test_api.py`` (shared fixtures via ``test_api_helpers``).
The endpoint stays a 200 liveness signal in every case; ``schema_ready``
is the separate readiness signal deploy gates assert.
"""

from __future__ import annotations

from unittest import mock

import pytest
from contextlib import nullcontext

# Import the module-local fixtures before the route module so they build
# ``yoke_core.api.main`` in production order without globally registering the
# helper module's generic fixture names.
from runtime.api.test_api_helpers import client, test_db  # noqa: F401
from runtime.api.fixtures.file_test_db import connect_test_db
import yoke_core.api.routes.items_health as items_health
from yoke_core.domain.migration_content_identity import (
    ContentIdentityStatus,
    ContentMismatch,
)


@pytest.fixture(autouse=True)
def manual_refresh(monkeypatch):
    """Control refresh timing independently of requests in probe unit tests."""
    monkeypatch.setattr(
        "yoke_core.api.health_refresh.health_refresh_lifespan", nullcontext
    )


def refreshed_health(client):
    items_health.initialize_health_metadata()
    items_health.refresh_health_snapshot()
    return client.get("/v1/health")


class TestHealthSchemaReady:
    def test_ready_when_probe_finds_all_tables(self, client, test_db):
        with mock.patch.object(
            items_health, "missing_readiness_tables", return_value=[]
        ):
            resp = refreshed_health(client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["schema_ready"] is True
        assert data["schema_missing_tables"] == []

    def test_missing_tables_report_not_ready_but_stay_live(self, client, test_db):
        with mock.patch.object(
            items_health,
            "missing_readiness_tables",
            return_value=["strategy_docs"],
        ):
            resp = refreshed_health(client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["schema_ready"] is False
        assert data["schema_missing_tables"] == ["strategy_docs"]

    def test_unreachable_db_reports_not_ready_but_stays_live(self, client, test_db):
        with mock.patch.object(
            items_health._main,
            "get_db_readonly",
            side_effect=OSError("connection refused"),
        ):
            resp = refreshed_health(client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["schema_ready"] is False
        assert data["schema_missing_tables"] == []

    def test_fixture_db_probe_runs_live(self, client, test_db):
        """No mocks: the probe's SQL executes against the fixture DB and the
        payload carries both readiness fields."""
        data = refreshed_health(client).json()
        assert isinstance(data["schema_ready"], bool)
        assert isinstance(data["schema_missing_tables"], list)


class TestHealthProbeConnectionCost:
    """HTTP reads reuse the last answer; background refresh owns convergence."""

    def test_repeated_calls_open_one_connection_once_ready(self, client, test_db):
        with mock.patch.object(
            items_health, "missing_readiness_tables", return_value=[]
        ):
            with mock.patch.object(
                items_health._main,
                "get_db_readonly",
                wraps=items_health._main.get_db_readonly,
            ) as get_db:
                first = refreshed_health(client).json()
                for _ in range(9):
                    client.get("/v1/health")

        assert get_db.call_count == 1
        assert first["schema_ready"] is True

    def test_ready_payload_is_stable_across_repeated_calls(self, client, test_db):
        with mock.patch.object(
            items_health, "missing_readiness_tables", return_value=[]
        ):
            first = refreshed_health(client).json()
            second = refreshed_health(client).json()

        assert first["schema_ready"] is second["schema_ready"] is True
        assert first["schema_missing_tables"] == second["schema_missing_tables"] == []

    def test_not_ready_process_keeps_probing_until_it_converges(self, client, test_db):
        """Background refresh must replace negative answers after schema
        convergence without depending on a request."""
        with mock.patch.object(
            items_health,
            "missing_readiness_tables",
            side_effect=[["strategy_docs"], ["strategy_docs"], []],
        ) as probe:
            assert refreshed_health(client).json()["schema_ready"] is False
            assert refreshed_health(client).json()["schema_ready"] is False
            assert refreshed_health(client).json()["schema_ready"] is True

        assert probe.call_count == 3

    def test_unreachable_db_keeps_probing(self, client, test_db):
        """A connection failure is not a readiness verdict — the next probe
        must still try."""
        with mock.patch.object(
            items_health._main,
            "get_db_readonly",
            side_effect=OSError("connection refused"),
        ) as get_db:
            assert refreshed_health(client).json()["schema_ready"] is False
            assert refreshed_health(client).json()["schema_ready"] is False

        assert get_db.call_count == 2


class TestHealthVersionHandshake:
    def test_payload_separates_api_contract_from_engine_version(
        self,
        client,
        test_db,
        monkeypatch,
    ):
        """``version`` is the /v1 route-shape token; ``engine_version`` is
        the installed engine dist the skew handshake compares."""
        monkeypatch.setattr(
            items_health,
            "advertised_engine_version",
            lambda *, build="": "3.2.1",
        )
        data = refreshed_health(client).json()
        assert data["version"] == items_health.API_CONTRACT_VERSION == "v1"
        assert data["engine_version"] == "3.2.1"

    def test_source_run_reports_empty_engine_version(
        self,
        client,
        test_db,
        monkeypatch,
    ):
        """No dist metadata (source run) degrades to an empty engine_version
        while the rest of the payload keeps working."""
        monkeypatch.setattr(
            items_health,
            "advertised_engine_version",
            lambda *, build="": "",
        )
        data = refreshed_health(client).json()
        assert data["engine_version"] == ""
        assert data["status"] == "ok"
        assert data["version"] == "v1"

    def test_image_build_with_unresolved_scm_metadata_reports_build_only(
        self,
        client,
        test_db,
        monkeypatch,
    ):
        """The image build SHA remains authoritative when wheel metadata
        only resolved to the setuptools-scm fallback."""
        from yoke_contracts import engine_version as ev

        monkeypatch.setenv("YOKE_BUILD_SHA", "abc123def456")
        monkeypatch.setattr(
            ev,
            "installed_engine_version",
            lambda: ev.UNRESOLVED_SCM_FALLBACK_VERSION,
        )
        data = refreshed_health(client).json()
        assert data["engine_version"] == ""
        assert data["build"] == "abc123def456"


class TestHealthMigrationContentIdentity:
    @staticmethod
    def _status(*, adoption=(), mismatches=()) -> ContentIdentityStatus:
        return ContentIdentityStatus(
            verified=(),
            adoption_required=tuple(adoption),
            adoptable=tuple(adoption),
            mismatches=tuple(mismatches),
            ledger_ahead=(),
        )

    def test_null_digest_is_visible_without_refusing_service(
        self,
        client,
        test_db,
    ):
        with (
            mock.patch.object(
                items_health,
                "migration_content_identity_status",
                return_value=self._status(adoption=("0001_existing",)),
            ),
            mock.patch.object(
                items_health, "stranded_by_applied_migrations", return_value=[]
            ),
            # This fixture applies a deliberately partial schema, so the
            # serving-surface probe legitimately reports what it is missing.
            # The subject here is content identity, not surface coverage.
            mock.patch.object(
                items_health, "unreadable_serving_surfaces", return_value=[]
            ),
            mock.patch.object(
                items_health,
                "yoke_migration_content_schema_is_prepared",
                return_value=True,
            ),
        ):
            data = refreshed_health(client).json()

        assert data["migration_content_matches"] is True
        assert data["migration_content_adoption_required"] == ["0001_existing"]
        assert data["migration_content_mismatches"] == []
        assert data["can_serve_this_database"] is True

    def test_mismatch_is_public_and_refuses_service(self, client, test_db):
        mismatch = ContentMismatch("0001_existing", "0" * 64, "1" * 64)
        with mock.patch.object(
            items_health,
            "migration_content_identity_status",
            return_value=self._status(mismatches=(mismatch,)),
        ):
            data = refreshed_health(client).json()

        assert data["migration_content_matches"] is False
        assert data["migration_content_adoption_required"] == []
        assert "0001_existing" in data["migration_content_mismatches"][0]
        assert data["can_serve_this_database"] is False

    def test_content_probe_runs_on_refresh_only_and_reset_clears(self, client, test_db):
        with mock.patch.object(
            items_health,
            "migration_content_identity_status",
            return_value=self._status(),
        ) as probe:
            refreshed_health(client)
            client.get("/v1/health")
            assert probe.call_count == 1

            items_health.reset_schema_readiness_cache()
            refreshed_health(client)

        assert probe.call_count == 2

    def test_content_probe_read_failure_fails_closed(self, client, test_db):
        with mock.patch.object(
            items_health,
            "migration_content_identity_status",
            side_effect=OSError("ledger read failed"),
        ):
            data = refreshed_health(client).json()

        assert data["migration_content_matches"] is False
        assert data["can_serve_this_database"] is False
        assert data["migration_content_mismatches"] == [
            "migration ledger content identity is unreadable"
        ]

    def test_dropped_evidence_guard_is_public_and_refuses_service(
        self,
        client,
        test_db,
    ):
        from yoke_core.domain.migration_yoke_ledger import ensure_yoke_migration_ledger

        conn = connect_test_db(test_db["db_path"])
        try:
            ensure_yoke_migration_ledger(conn)
            trigger = conn.execute(
                "SELECT tgname FROM pg_trigger "
                "WHERE tgrelid = to_regclass('migration_content_adoptions') "
                "AND NOT tgisinternal ORDER BY tgname LIMIT 1"
            ).fetchone()[0]
            conn.execute(f'DROP TRIGGER "{trigger}" ON migration_content_adoptions')
            conn.commit()
        finally:
            conn.close()

        data = refreshed_health(client).json()

        assert data["migration_content_matches"] is True
        assert data["migration_content_evidence_ready"] is False
        assert data["can_serve_this_database"] is False
