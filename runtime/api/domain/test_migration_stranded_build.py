"""A build too old to serve what its database applied must not report healthy.

The fixture is the real retirement entry rather than a synthetic drop: it
removed ``items.flow`` and ``path_claims.item_id``, whose disappearance broke
item creation and path-claim registration fleet-wide. Those are the outages
this probe exists to convert from silent broken reads into a failed container.
"""

from __future__ import annotations

import importlib
import sqlite3

from yoke_core.domain import schema_readiness

RETIREMENT_ENTRY_NAME = "0001_retire_superseded_surfaces"

# A history entry's filename stem starts with its ordering digits, so it is
# not a valid identifier and cannot be imported by name.
retirement_entry = importlib.import_module(
    f"yoke_core.domain.migrations.{RETIREMENT_ENTRY_NAME}"
)


def _ledger(*rows: tuple[str, str | None]) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = None
    conn.execute(
        "CREATE TABLE applied_migrations ("
        "migration_name TEXT PRIMARY KEY, applied_at TEXT NOT NULL, "
        "applied_by TEXT, minimum_serving_version TEXT)"
    )
    for name, floor in rows:
        conn.execute(
            "INSERT INTO applied_migrations "
            "(migration_name, applied_at, applied_by, minimum_serving_version) "
            "VALUES (?, 'now', 'test', ?)",
            (name, floor),
        )
    conn.commit()
    return conn


class TestStrandedBuildIsReported:
    def test_build_older_than_the_recorded_floor_is_stranded(self) -> None:
        conn = _ledger((RETIREMENT_ENTRY_NAME, "0.1.1+launch.181"))

        findings = schema_readiness.stranded_by_applied_migrations(
            conn, "0.1.1+launch.169"
        )

        assert len(findings) == 1
        finding = findings[0]
        # An operator reading a failed container needs all four facts.
        assert RETIREMENT_ENTRY_NAME in finding
        assert "0.1.1+launch.181" in finding
        assert "0.1.1+launch.169" in finding
        assert "Deploy" in finding

    def test_build_at_the_floor_serves(self) -> None:
        conn = _ledger((RETIREMENT_ENTRY_NAME, "0.1.1+launch.181"))

        assert not schema_readiness.stranded_by_applied_migrations(
            conn, "0.1.1+launch.181"
        )

    def test_newer_build_serves(self) -> None:
        conn = _ledger((RETIREMENT_ENTRY_NAME, "0.1.1+launch.181"))

        assert not schema_readiness.stranded_by_applied_migrations(
            conn, "0.1.1+launch.200"
        )


class TestAbsentFloorIsNotAViolation:
    def test_row_without_a_recorded_floor_is_not_a_finding(self) -> None:
        """The majority state on any database that applied before floors existed.

        Reading "no record" as "violation" would report most of an existing
        fleet as stranded on the first boot that could see it.
        """
        conn = _ledger((RETIREMENT_ENTRY_NAME, None))

        assert not schema_readiness.stranded_by_applied_migrations(conn, "0.0.1")

    def test_empty_ledger_is_not_a_finding(self) -> None:
        conn = _ledger()

        assert not schema_readiness.stranded_by_applied_migrations(conn, "0.0.1")

    def test_absent_ledger_table_does_not_refuse_service(self) -> None:
        """Cannot-tell must not manufacture a fleet-wide refusal."""
        conn = sqlite3.connect(":memory:")

        assert not schema_readiness.stranded_by_applied_migrations(conn, "0.0.1")


class TestSourceCheckoutIsNeverStranded:
    def test_unresolved_running_version_yields_no_findings(self) -> None:
        """A source tree advertises its last tag, not its code.

        Comparing it as that tag would strand every developer machine on the
        entry that tree just authored.
        """
        conn = _ledger((RETIREMENT_ENTRY_NAME, "99.0.0"))

        assert not schema_readiness.stranded_by_applied_migrations(conn, "")


class TestMalformedFloorIsVisibleNotFatal:
    def test_unparseable_floor_is_reported_as_a_repair_finding(self) -> None:
        conn = _ledger((RETIREMENT_ENTRY_NAME, "not-a-version"))

        findings = schema_readiness.stranded_by_applied_migrations(conn, "0.1.2")

        assert len(findings) == 1
        assert "repair" in findings[0]


class TestRetirementEntryDeclaresItsFloor:
    def test_the_real_destructive_entry_carries_a_declaration(self) -> None:
        """The mandated fixture must itself satisfy the authoring contract."""
        declared = getattr(retirement_entry, "MINIMUM_SERVING_VERSION", None)

        assert declared, "the retirement entry must declare its serving floor"

    def test_the_retirement_entry_removes_the_surfaces_it_claims(self) -> None:
        retired = dict(retirement_entry.SUPERSEDED_COLUMNS)

        assert retired["items"] or retired["path_claims"]
