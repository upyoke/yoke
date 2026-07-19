from __future__ import annotations

from datetime import datetime, timedelta, timezone

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_schema
from yoke_core.domain import pack_projection


def test_project_report_distinguishes_available_installed_and_update_stale(
    monkeypatch,
) -> None:
    db_name = pg_testdb.create_test_database()
    try:
        conn = pg_testdb.connect_test_database(db_name)
        try:
            apply_fixture_schema(conn)
            monkeypatch.setattr(pack_projection, "catalog_rows", _catalog)
            pack_projection.converge_pack_catalog(conn)
            pack_projection.report_project_packs(
                conn,
                project="yoke",
                receipt_digest="a" * 64,
                packs=[
                    {"slug": "current", "version": "1.0.0", "file_count": 2},
                    {"slug": "outdated", "version": "1.0.0", "file_count": 3},
                ],
            )
            conn.commit()

            result = pack_projection.list_project_pack_status(conn, project="yoke")
        finally:
            conn.close()

        rows = {row["slug"]: row for row in result["packs"]}
        assert rows["available"]["status"] == "available"
        assert rows["current"]["status"] == "installed"
        assert rows["current"]["stale_reasons"] == []
        assert rows["outdated"]["status"] == "stale"
        assert rows["outdated"]["stale_reasons"] == ["update_available"]
        assert result["repository_report"]["fresh"] is True
        assert result["repository_report"]["pack_count"] == 2
    finally:
        pg_testdb.drop_test_database(db_name)


def test_expired_repository_report_is_labeled_stale() -> None:
    db_name = pg_testdb.create_test_database()
    try:
        conn = pg_testdb.connect_test_database(db_name)
        try:
            apply_fixture_schema(conn)
            pack_projection.create_pack_projection_tables(conn)
            conn.execute(
                "INSERT INTO pack_catalog("
                "slug,name,description,latest_version,dependencies_json,"
                "documentation,file_count,observed_at"
                ") VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    "current",
                    "Current",
                    "Current Pack.",
                    "1.0.0",
                    "[]",
                    "docs/packs/current/README.md",
                    2,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            pack_projection.report_project_packs(
                conn,
                project="yoke",
                receipt_digest="b" * 64,
                packs=[
                    {"slug": "current", "version": "1.0.0", "file_count": 2}
                ],
            )
            expired = datetime.now(timezone.utc) - timedelta(days=2)
            conn.execute(
                "UPDATE project_pack_reports SET reported_at=%s WHERE project_id="
                "(SELECT id FROM projects WHERE slug=%s)",
                (expired.isoformat(), "yoke"),
            )
            conn.commit()

            result = pack_projection.list_project_pack_status(conn, project="yoke")
        finally:
            conn.close()

        assert result["packs"][0]["status"] == "stale"
        assert result["packs"][0]["stale_reasons"] == [
            "repository_report_expired"
        ]
        assert result["repository_report"]["fresh"] is False
    finally:
        pg_testdb.drop_test_database(db_name)


def _catalog() -> list[dict[str, object]]:
    return [
        {
            "slug": "available",
            "name": "Available",
            "description": "Available Pack.",
            "latest_version": "1.0.0",
            "dependencies": [],
            "documentation": "docs/packs/available/README.md",
            "file_count": 1,
        },
        {
            "slug": "current",
            "name": "Current",
            "description": "Current Pack.",
            "latest_version": "1.0.0",
            "dependencies": [],
            "documentation": "docs/packs/current/README.md",
            "file_count": 2,
        },
        {
            "slug": "outdated",
            "name": "Outdated",
            "description": "Outdated Pack.",
            "latest_version": "2.0.0",
            "dependencies": ["current"],
            "documentation": "docs/packs/outdated/README.md",
            "file_count": 4,
        },
    ]
