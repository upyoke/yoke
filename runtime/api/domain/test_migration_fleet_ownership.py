"""A table its serving role does not own can never gain a column again.

The boot converge adds columns to its own tables, which Postgres permits only
for the owner. So a table created by another role is a latent boot failure
that fires on the next release touching it. This is the check that finds it,
and it has to read the live database: a restored copy cannot answer the
question, because ``pg_restore --no-owner`` hands every object to whoever
restores it.
"""

from __future__ import annotations

from typing import Any, List, Sequence, Tuple

import pytest

from yoke_core.domain import migration_fleet_ownership as ownership


class _Cursor:
    def __init__(self, rows: Sequence[tuple]) -> None:
        self._rows = list(rows)

    def fetchall(self) -> list:
        return list(self._rows)


class _Connection:
    """Answers the ownership probe and records what it was asked to alter."""

    def __init__(self, rows: Sequence[Tuple[str, str]]) -> None:
        self._rows = list(rows)
        self.statements: List[str] = []
        self.closed = False

    def execute(self, sql: str, *_args: Any) -> _Cursor:
        if sql.strip().startswith("SELECT"):
            return _Cursor(self._rows)
        self.statements.append(" ".join(sql.split()))
        return _Cursor([])

    def commit(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


UNIFORM = [("items", "tenant"), ("events", "tenant"), ("claims", "tenant")]
DRIFTED = [("items", "tenant"), ("events", "tenant"), ("ledger", "admin")]


class TestInspect:
    def test_uniform_ownership_reports_no_drift(self) -> None:
        report = ownership.inspect(_Connection(UNIFORM))

        assert report.uniform
        assert report.expected_owner == "tenant"
        assert report.table_count == 3

    def test_a_table_owned_by_another_role_is_drift(self) -> None:
        report = ownership.inspect(_Connection(DRIFTED))

        assert not report.uniform
        assert report.drifted == (("ledger", "admin"),)

    def test_summary_names_the_table_and_both_roles(self) -> None:
        # An operator reading this at 3am needs the noun, not a count.
        summary = ownership.inspect(_Connection(DRIFTED)).summary

        assert "ledger" in summary
        assert "admin" in summary
        assert "tenant" in summary

    def test_the_expected_owner_can_be_stated_outright(self) -> None:
        report = ownership.inspect(_Connection(UNIFORM), expected_owner="someone_else")

        assert not report.uniform
        assert len(report.drifted) == 3

    def test_an_empty_database_is_not_a_violation(self) -> None:
        """A database with no tables tells us nothing, which is not a finding."""
        report = ownership.inspect(_Connection([]))

        assert report.uniform
        assert report.table_count == 0


class TestMajorityOwner:
    def test_the_majority_is_the_serving_role(self) -> None:
        assert ownership.majority_owner(DRIFTED) == "tenant"

    def test_a_tie_resolves_the_same_way_every_run(self) -> None:
        # A tie is a report of drift whichever side wins, but an unstable
        # answer would make the same database report differently run to run.
        tied = [("a", "one"), ("b", "two")]

        assert ownership.majority_owner(tied) == ownership.majority_owner(tied)


class TestRealign:
    def test_alters_only_the_named_table(self) -> None:
        conn = _Connection(DRIFTED)

        altered = ownership.realign(conn, tables=["ledger"], owner="tenant")

        assert altered == ["ledger"]
        assert conn.statements == ['ALTER TABLE public."ledger" OWNER TO "tenant"']

    def test_skips_a_table_that_is_not_there(self) -> None:
        conn = _Connection(DRIFTED)

        assert ownership.realign(conn, tables=["absent"], owner="tenant") == []
        assert conn.statements == []


class TestPreflightReadsTheLiveDatabase:
    def test_the_rehearsal_copy_cannot_answer_this(self) -> None:
        """The reason this check exists outside the rehearsal, asserted.

        ``pg_dump --no-owner`` is what the preflight restores with, and it
        assigns everything to whoever restores it. So a drifted source and a
        clean source produce an identical copy, and any check running against
        the copy reports the same answer for both. A green preflight on such a
        copy is a true statement about the copy and says nothing about the
        tenant — which is how one preceded a production control plane
        crash-looping at boot.
        """
        from yoke_core.domain import migration_fleet_preflight

        restore_flags = migration_fleet_preflight.rehearse.__doc__ or ""
        assert "live database" in restore_flags

        drifted_source = ownership.inspect(_Connection(DRIFTED))
        clean_source = ownership.inspect(_Connection(UNIFORM))
        assert not drifted_source.uniform
        assert clean_source.uniform

        # What both look like once restored with --no-owner: one owner.
        as_restored = [(table, "restorer") for table, _owner in DRIFTED]
        assert ownership.inspect(_Connection(as_restored)).uniform

    def test_preflight_refuses_a_drifted_database_before_rehearsing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from yoke_core.domain import db_backend, migration_fleet_preflight

        monkeypatch.setattr(
            db_backend, "connect_psycopg", lambda *_a, **_k: _Connection(DRIFTED)
        )
        verdict = migration_fleet_preflight._live_ownership_verdict("dsn", "tenant_1")

        assert verdict is not None
        assert not verdict.passed
        assert "ledger" in verdict.detail

    def test_preflight_proceeds_when_ownership_is_uniform(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from yoke_core.domain import db_backend, migration_fleet_preflight

        monkeypatch.setattr(
            db_backend, "connect_psycopg", lambda *_a, **_k: _Connection(UNIFORM)
        )

        assert (
            migration_fleet_preflight._live_ownership_verdict("dsn", "tenant_1") is None
        )

    def test_an_unreadable_database_fails_rather_than_passes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not being able to check is not the same as having checked."""
        from yoke_core.domain import db_backend, migration_fleet_preflight

        def refuse(*_a: Any, **_k: Any):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(db_backend, "connect_psycopg", refuse)
        verdict = migration_fleet_preflight._live_ownership_verdict("dsn", "tenant_1")

        assert verdict is not None
        assert not verdict.passed


class TestSummaryStaysReadable:
    def test_a_whole_database_mismatch_does_not_bury_the_sentence(self) -> None:
        # Naming every row turned a real run into a hundred-table wall that
        # hid the one clause explaining it: the expected owner was wrong.
        wide = [(f"table_{n}", "other") for n in range(100)]

        summary = ownership.inspect(_Connection(wide), expected_owner="tenant").summary

        assert "100 of 100" in summary
        assert "and 94 more" in summary
        assert summary.count("owned by") == ownership.SUMMARY_NAME_LIMIT

    def test_a_small_drift_set_is_named_in_full(self) -> None:
        summary = ownership.inspect(_Connection(DRIFTED)).summary

        assert "more" not in summary
        assert "ledger owned by admin" in summary
