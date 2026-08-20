"""A build must ask the database whether the shapes it reads are still there.

The declared serving floor is hand-authored, and a wrong one reported a fleet
able to serve a schema whose columns every request was failing to read. This
probe cannot be wrong in that direction: it compares the catalog the running
artifact ships against the catalog the database actually has.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from yoke_core.domain import schema_readiness
from yoke_core.domain.schema_expected_catalog import parse_expected_schema

# The shape of the entry that took production QA down: a renamed column the
# serving build still read.
BUILD_READS: Dict[str, Dict[str, str]] = {
    "qa_methods": {"id": "TEXT", "required_capability_kind": "TEXT"},
    "items": {"id": "INTEGER", "title": "TEXT"},
}


class _Catalog:
    """A connection that answers only the probe's ``information_schema`` read."""

    def __init__(self, rows: Sequence[Tuple[str, str]] | None) -> None:
        self._rows = rows

    def execute(self, _sql: str) -> "_Catalog":
        if self._rows is None:
            raise RuntimeError("catalog is unreadable")
        return self

    def fetchall(self) -> List[Tuple[str, str]]:
        assert self._rows is not None
        return list(self._rows)


def _catalog_of(tables: Dict[str, Dict[str, str]]) -> _Catalog:
    return _Catalog(
        [(table, column) for table, columns in tables.items() for column in columns]
    )


class TestSurfacesThisBuildReads:
    def test_a_matching_database_reports_nothing(self) -> None:
        assert (
            schema_readiness.unreadable_serving_surfaces(
                _catalog_of(BUILD_READS), BUILD_READS
            )
            == []
        )

    def test_a_database_carrying_more_than_this_build_reads_still_serves(self) -> None:
        ahead = {
            "qa_methods": {**BUILD_READS["qa_methods"], "runner_gloss": "TEXT"},
            "items": BUILD_READS["items"],
            "strategy_docs": {"id": "INTEGER"},
        }
        assert (
            schema_readiness.unreadable_serving_surfaces(
                _catalog_of(ahead), BUILD_READS
            )
            == []
        )

    def test_a_column_the_build_reads_that_a_migration_removed_is_named(self) -> None:
        migrated = {
            "qa_methods": {"id": "TEXT", "required_capability_kinds": "TEXT"},
            "items": BUILD_READS["items"],
        }

        findings = schema_readiness.unreadable_serving_surfaces(
            _catalog_of(migrated), BUILD_READS
        )

        assert len(findings) == 1
        assert "qa_methods" in findings[0]
        assert "required_capability_kind" in findings[0]

    def test_a_missing_table_is_one_finding_not_one_per_column(self) -> None:
        findings = schema_readiness.unreadable_serving_surfaces(
            _catalog_of({"items": BUILD_READS["items"]}), BUILD_READS
        )

        assert len(findings) == 1
        assert findings[0].startswith("qa_methods:")

    def test_an_unreadable_catalog_refuses_rather_than_passing(self) -> None:
        findings = schema_readiness.unreadable_serving_surfaces(
            _Catalog(None), BUILD_READS
        )

        assert len(findings) == 1
        assert "unreadable" in findings[0]

    def test_the_probe_defaults_to_the_catalog_this_build_ships(self) -> None:
        # No declared expectation: the packaged catalog is what the running
        # code reads, and an empty database therefore cannot serve it.
        findings = schema_readiness.unreadable_serving_surfaces(_Catalog([]))

        assert findings
        assert len(findings) == len(parse_expected_schema())


class TestProbeIsIndependentOfDeclaredFloors:
    def test_no_ledger_or_floor_participates_in_the_answer(self) -> None:
        # The incident's signature: the ledger says current, the floor says
        # serviceable, and the column the code reads is gone anyway.
        conn: Any = _catalog_of({"items": BUILD_READS["items"]})

        assert schema_readiness.unreadable_serving_surfaces(conn, BUILD_READS)


class TestTheCatalogIsLoadBearing:
    """A born universe must satisfy the catalog of the build that serves it.

    The probe gates serving, so a catalog naming a surface real universes do
    not carry would refuse every container — the same outage from the other
    direction. The subject is the whole birth chain rather than the boot
    converge alone, because convergence creates the core schema while several
    subsystems create their own tables at birth, and every served universe has
    been through both.
    """

    def test_a_born_universe_can_serve_itself(self) -> None:
        import psycopg

        from runtime.api.fixtures import pg_testdb
        from yoke_core.domain.environment_bootstrap import run_init_chain_at_dsn

        name = pg_testdb.create_test_database()
        dsn = pg_testdb.dsn_for_test_database(name)
        try:
            run_init_chain_at_dsn(dsn, emit=lambda _line: None)
            with psycopg.connect(dsn) as conn:
                assert schema_readiness.unreadable_serving_surfaces(conn) == []
        finally:
            pg_testdb.drop_test_database(name)
