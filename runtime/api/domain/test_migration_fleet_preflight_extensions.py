"""A rehearsal copy must run the extension versions its source runs.

A dump names its extensions without versions, so a cluster one Postgres
release ahead installs newer ones and a view compiled against the source's row
type fails to restore as ambiguous. The fix stages the source's versions into
the fresh copy first, including the schema an extension lives in, and never
asks the live source to change. The real dump/restore round trip is in
``test_migration_fleet_preflight_extension_restore``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import (
    migration_fleet_preflight as preflight,
    migration_fleet_preflight_extensions as extensions,
    migration_fleet_preflight_transfer as transfer,
)
from yoke_core.domain.migration_fleet_preflight import RehearsalPlan
from yoke_core.domain.postgres_cluster import ClusterSpec

STATISTICS_EXTENSION = "pg_stat_statements"

#: Where prod and stage actually keep the statistics extension: a schema the
#: dump creates, holding a view the tenant depends on.
DUMP_CREATED_SCHEMA = "statement_statistics"

#: The rehearsal never reaches convergence in these tests: a refusal stops
#: before the copy, and the ordering test replaces the converge step.
UNREACHED_PLAN = RehearsalPlan(
    ("0001_first",),
    pending_names=lambda _conn, _history: (),
    converge=lambda _conn, _dsn: None,
)


def _catalog(monkeypatch, *, defaults, offered, server_version="17.10") -> None:
    """Answer the cluster-capability read without a cluster."""
    monkeypatch.setattr(
        extensions,
        "cluster_extensions",
        lambda _spec: extensions.ClusterExtensions(
            server_version=server_version,
            default_versions=defaults,
            offered_versions=frozenset(offered),
        ),
    )


def _source(name=STATISTICS_EXTENSION, version="1.10", schema="public"):
    return extensions.SourceExtension(name, version, schema)


class TestExtensionPins:
    def test_a_version_the_cluster_already_defaults_to_needs_no_pin(
        self, monkeypatch,
    ) -> None:
        # The dump's own CREATE EXTENSION produces this one correctly, so
        # pinning it would be work that changes nothing.
        _catalog(
            monkeypatch,
            defaults={STATISTICS_EXTENSION: "1.11"},
            offered={(STATISTICS_EXTENSION, "1.11")},
        )

        assert extensions.extension_pins(object(), [_source(version="1.11")]) == ()

    def test_a_version_the_cluster_would_get_wrong_is_pinned(
        self, monkeypatch,
    ) -> None:
        _catalog(
            monkeypatch,
            defaults={STATISTICS_EXTENSION: "1.11", "plpgsql": "1.0"},
            offered={
                (STATISTICS_EXTENSION, "1.10"),
                (STATISTICS_EXTENSION, "1.11"),
                ("plpgsql", "1.0"),
            },
        )

        pins = extensions.extension_pins(
            object(),
            [_source(), _source("plpgsql", "1.0", "pg_catalog")],
        )

        assert [(pin.name, pin.version) for pin in pins] == [
            (STATISTICS_EXTENSION, "1.10"),
        ]

    def test_the_schema_an_extension_lives_in_never_makes_it_unpinnable(
        self, monkeypatch,
    ) -> None:
        """The fleet's own shape: the extension sits in a dump-created schema.

        Refusing here would block the very tenants this exists for, and the
        only recovery would be moving an extension in a live database.
        """
        _catalog(
            monkeypatch,
            defaults={STATISTICS_EXTENSION: "1.11"},
            offered={(STATISTICS_EXTENSION, "1.10")},
        )

        pins = extensions.extension_pins(
            object(), [_source(schema=DUMP_CREATED_SCHEMA)]
        )

        assert [(pin.name, pin.schema) for pin in pins] == [
            (STATISTICS_EXTENSION, DUMP_CREATED_SCHEMA),
        ]

    def test_a_version_the_cluster_cannot_install_refuses_with_recovery(
        self, monkeypatch,
    ) -> None:
        _catalog(
            monkeypatch,
            defaults={STATISTICS_EXTENSION: "1.11"},
            offered={(STATISTICS_EXTENSION, "1.10"), (STATISTICS_EXTENSION, "1.11")},
        )

        with pytest.raises(extensions.CopyFidelityError) as excinfo:
            extensions.extension_pins(object(), [_source(version="1.12")])

        message = str(excinfo.value)
        assert f"{STATISTICS_EXTENSION} 1.12" in message
        assert "PostgreSQL 17.10" in message
        assert "it offers 1.10, 1.11" in message
        assert "would install 1.11 instead" in message
        # A refusal that does not say what to do just moves the outage — and
        # what it says to do must never be "change the live database".
        assert "Install the contrib build" in message
        assert "ALTER EXTENSION" not in message
        assert "SET SCHEMA" not in message

    def test_an_extension_the_cluster_has_never_heard_of_refuses(
        self, monkeypatch,
    ) -> None:
        _catalog(monkeypatch, defaults={}, offered=set())

        with pytest.raises(extensions.CopyFidelityError, match="no version"):
            extensions.extension_pins(object(), [_source("vector", "0.7.0")])


class _RecordingConn:
    """Collects the composed DDL instead of executing it."""

    def __init__(self, statements: list) -> None:
        self._statements = statements

    def execute(self, statement) -> None:
        self._statements.append(statement.as_string(None))

    def close(self) -> None:
        return None


class TestStagingPins:
    @pytest.fixture
    def statements(self, monkeypatch) -> list:
        from yoke_core.domain import db_backend

        recorded: list = []
        monkeypatch.setattr(
            db_backend,
            "_open_native_postgres",
            lambda *_a, **_kw: _RecordingConn(recorded),
        )
        return recorded

    @pytest.fixture
    def omitted(self, monkeypatch) -> list:
        calls: list = []
        monkeypatch.setattr(
            transfer,
            "restore_list_omitting_schemas",
            lambda _spec, _dump, schemas, path: calls.append((tuple(schemas), path)),
        )
        return calls

    def _stage(self, tmp_path: Path, pins):
        return extensions.stage_pinned_extensions(
            ClusterSpec(root=tmp_path, superuser="rehearsal"),
            "migration_rehearsal_tenant",
            pins,
            dump=tmp_path / "tenant.dump",
            list_path=tmp_path / "tenant.restore-list",
        )

    def test_staging_nothing_opens_no_connection(self, monkeypatch) -> None:
        from yoke_core.domain import db_backend

        monkeypatch.setattr(
            db_backend,
            "_open_native_postgres",
            lambda *_a, **_kw: pytest.fail("an empty pin set must not connect"),
        )

        assert extensions.stage_pinned_extensions(
            object(), "copy", (), dump=Path("d"), list_path=Path("l")
        ) is None

    def test_a_pin_quotes_its_identifiers_and_its_version(
        self, statements, omitted, tmp_path: Path,
    ) -> None:
        """Names and versions come from the source's catalog, not from us."""
        use_list = self._stage(
            tmp_path,
            [_source("uuid-ossp", "1.1"), _source("plpgsql", "1.0", "pg_catalog")],
        )

        assert statements == [
            'CREATE EXTENSION "uuid-ossp" WITH SCHEMA "public" VERSION \'1.1\'',
            'CREATE EXTENSION "plpgsql" WITH SCHEMA "pg_catalog" VERSION \'1.0\'',
        ]
        # A database already has these schemas, so the dump needs no editing.
        assert use_list is None
        assert omitted == []

    def test_a_dump_created_schema_is_staged_and_then_skipped_on_restore(
        self, statements, omitted, tmp_path: Path,
    ) -> None:
        use_list = self._stage(tmp_path, [_source(schema=DUMP_CREATED_SCHEMA)])

        # Schema first: the extension cannot be created into a schema that is
        # not there yet.
        assert statements == [
            f'CREATE SCHEMA "{DUMP_CREATED_SCHEMA}"',
            f'CREATE EXTENSION "{STATISTICS_EXTENSION}" WITH SCHEMA '
            f'"{DUMP_CREATED_SCHEMA}" VERSION \'1.10\'',
        ]
        assert use_list == tmp_path / "tenant.restore-list"
        assert omitted == [((DUMP_CREATED_SCHEMA,), use_list)]

    def test_two_pins_sharing_one_schema_create_it_once(
        self, statements, omitted, tmp_path: Path,
    ) -> None:
        self._stage(
            tmp_path,
            [
                _source(schema=DUMP_CREATED_SCHEMA),
                _source("pgstattuple", "1.5", DUMP_CREATED_SCHEMA),
            ],
        )

        assert statements.count(f'CREATE SCHEMA "{DUMP_CREATED_SCHEMA}"') == 1
        assert omitted[0][0] == (DUMP_CREATED_SCHEMA,)


def _raise(error: Exception):
    raise error


def _rehearse_tenant(tmp_path: Path, source_dsn: str):
    return preflight.rehearse(
        source_dsn,
        database="tenant_1",
        plan=UNREACHED_PLAN,
        spec=ClusterSpec(root=tmp_path / "cluster", superuser="rehearsal"),
        work_dir=tmp_path / "work",
    )


class TestRehearsalSequence:
    """Where staging sits in :func:`migration_fleet_preflight.rehearse`."""

    @pytest.fixture(autouse=True)
    def _ownership_already_cleared(self, monkeypatch) -> None:
        monkeypatch.setattr(
            preflight, "_live_ownership_verdict", lambda *_a, **_kw: None
        )
        monkeypatch.setattr(extensions, "source_extensions", lambda _dsn: (_source(),))

    def test_a_copy_that_cannot_be_faithful_fails_before_anything_is_dumped(
        self, monkeypatch, tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            extensions,
            "extension_pins",
            lambda *_a: _raise(
                extensions.CopyFidelityError("cannot install 1.10 for host=db pw=s3cret")
            ),
        )
        monkeypatch.setattr(
            transfer,
            "dump_database",
            lambda *_a, **_kw: pytest.fail("a refusal must precede the copy"),
        )

        verdict = _rehearse_tenant(tmp_path, "host=db pw=s3cret")

        assert not verdict.passed
        assert "could not copy faithfully" in verdict.detail
        # The refusal travels to a capture an operator reads; the source DSN
        # must not travel with it.
        assert "s3cret" not in verdict.detail
        assert "<dsn>" in verdict.detail
        assert not verdict.pending_evaluated

    def test_the_copy_is_staged_between_creating_it_and_restoring_into_it(
        self, monkeypatch, tmp_path: Path,
    ) -> None:
        order: list[str] = []
        monkeypatch.setattr(extensions, "extension_pins", lambda *_a: (_source(),))
        monkeypatch.setattr(
            extensions,
            "stage_pinned_extensions",
            lambda _spec, _copy, pins, **kw: (
                order.append(f"stage:{pins[0].version}") or kw["list_path"]
            ),
        )
        for name in ("dump_database", "drop_copy", "create_copy"):
            monkeypatch.setattr(
                transfer, name, lambda *_a, _n=name, **_kw: order.append(_n)
            )
        monkeypatch.setattr(
            transfer,
            "restore_copy",
            lambda *_a, **kw: order.append(f"restore:{kw['use_list'].name}"),
        )
        monkeypatch.setattr(
            preflight,
            "_converge_copy",
            lambda *_a: preflight.Verdict("tenant_1", True, "converged"),
        )

        assert _rehearse_tenant(tmp_path, "dsn").passed
        assert order == [
            "dump_database", "drop_copy", "create_copy", "stage:1.10",
            "restore:tenant_1.restore-list", "drop_copy",
        ]
