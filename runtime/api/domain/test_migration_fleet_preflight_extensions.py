"""A rehearsal copy must run the extension versions its source runs.

A dump names its extensions without versions, so a cluster one Postgres
release ahead installs newer ones and a view compiled against the source's row
type fails to restore as ambiguous. A copy that cannot be built faithfully has
to say so before it is built, never converge and report a pass.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from yoke_core.domain import (
    migration_fleet_preflight as preflight,
    migration_fleet_preflight_extensions as extensions,
    migration_fleet_preflight_transfer as transfer,
    postgres_cluster,
)
from yoke_core.domain.migration_fleet_preflight import RehearsalPlan
from yoke_core.domain.postgres_cluster import ClusterSpec

STATISTICS_EXTENSION = "pg_stat_statements"

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
        # A refusal that does not say what to do just moves the outage.
        assert "Install the contrib build" in message

    def test_an_extension_the_cluster_has_never_heard_of_refuses(
        self, monkeypatch,
    ) -> None:
        _catalog(monkeypatch, defaults={}, offered=set())

        with pytest.raises(extensions.CopyFidelityError, match="no version"):
            extensions.extension_pins(object(), [_source("vector", "0.7.0")])

    def test_an_extension_outside_a_pinnable_schema_refuses(
        self, monkeypatch,
    ) -> None:
        # Pinning it would need its schema first, and the dump carries a plain
        # CREATE SCHEMA for that schema — a duplicate that fails the restore.
        # Refusing beats trading one restore error for another.
        _catalog(
            monkeypatch,
            defaults={STATISTICS_EXTENSION: "1.11"},
            offered={(STATISTICS_EXTENSION, "1.10")},
        )

        with pytest.raises(extensions.CopyFidelityError) as excinfo:
            extensions.extension_pins(object(), [_source(schema="ext_home")])

        message = str(excinfo.value)
        assert "'ext_home'" in message
        assert "CREATE SCHEMA" in message
        assert "SET SCHEMA public" in message


class TestPinStatements:
    def test_pinning_nothing_opens_no_connection(self, monkeypatch) -> None:
        from yoke_core.domain import db_backend

        monkeypatch.setattr(
            db_backend,
            "_open_native_postgres",
            lambda *_a, **_kw: pytest.fail("an empty pin set must not connect"),
        )

        extensions.pin_extension_versions(object(), "copy", ())

    def test_a_pin_quotes_its_identifiers_and_its_version(
        self, monkeypatch, tmp_path: Path,
    ) -> None:
        """Names and versions come from the source's catalog, not from us."""
        statements = []

        class _Conn:
            def execute(self, statement) -> None:
                statements.append(statement.as_string(None))

            def close(self) -> None:
                return None

        from yoke_core.domain import db_backend

        monkeypatch.setattr(
            db_backend, "_open_native_postgres", lambda *_a, **_kw: _Conn()
        )

        extensions.pin_extension_versions(
            ClusterSpec(root=tmp_path, superuser="rehearsal"),
            "migration_rehearsal_tenant",
            [_source("uuid-ossp", "1.1"), _source("plpgsql", "1.0", "pg_catalog")],
        )

        assert statements == [
            'CREATE EXTENSION "uuid-ossp" WITH SCHEMA "public" VERSION \'1.1\'',
            'CREATE EXTENSION "plpgsql" WITH SCHEMA "pg_catalog" VERSION \'1.0\'',
        ]


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
    """Where the pin sits in :func:`migration_fleet_preflight.rehearse`."""

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

    def test_the_copy_is_pinned_between_creating_it_and_restoring_into_it(
        self, monkeypatch, tmp_path: Path,
    ) -> None:
        order: list[str] = []
        monkeypatch.setattr(extensions, "extension_pins", lambda *_a: (_source(),))
        monkeypatch.setattr(
            extensions,
            "pin_extension_versions",
            lambda _spec, _copy, pins: order.append(f"pin:{pins[0].version}"),
        )
        for name in ("dump_database", "drop_copy", "create_copy", "restore_copy"):
            monkeypatch.setattr(
                transfer, name, lambda *_a, _n=name, **_kw: order.append(_n)
            )
        monkeypatch.setattr(
            preflight,
            "_converge_copy",
            lambda *_a: preflight.Verdict("tenant_1", True, "converged"),
        )

        assert _rehearse_tenant(tmp_path, "dsn").passed
        assert order == ["dump_database", "drop_copy", "create_copy",
                         "pin:1.10", "restore_copy", "drop_copy"]


def _ordered(version: str) -> tuple:
    return tuple(int(part) for part in version.split("."))


def _older_offered_version(spec: ClusterSpec, default: str) -> "str | None":
    """The highest installable statistics-extension version below *default*."""
    probe = postgres_cluster.psql(
        spec,
        "SELECT version FROM pg_available_extension_versions "
        f"WHERE name = '{STATISTICS_EXTENSION}'",
    )
    offered = {line.strip() for line in probe.stdout.splitlines() if line.strip()}
    older = sorted(v for v in offered if _ordered(v) < _ordered(default))
    return older[-1] if older else None


@pytest.mark.skipif(
    shutil.which("initdb") is None,
    reason="system Postgres binaries not on PATH",
)
def test_a_view_over_the_extension_function_restores_at_the_source_version():
    """The real dump/restore round trip the fleet preflight failed on.

    The scratch root sits directly under the OS temp dir because unix socket
    paths cap near 103 bytes and pytest's nested tmp_path blows that on macOS.
    """
    scratch = Path(tempfile.mkdtemp(prefix="yoke-extpin-", dir="/tmp"))
    spec = ClusterSpec(
        root=scratch,
        superuser="rehearsaluser",
        server_settings=(("fsync", "off"),),
        stop_mode="immediate",
    )
    try:
        assert postgres_cluster.ensure_started(spec) == 0
        default = postgres_cluster.psql(
            spec,
            "SELECT default_version FROM pg_available_extensions "
            f"WHERE name = '{STATISTICS_EXTENSION}'",
        ).stdout.strip()
        if not default:
            pytest.skip(f"{STATISTICS_EXTENSION} is not available on this cluster")
        older = _older_offered_version(spec, default)
        if older is None:
            pytest.skip(f"this cluster offers only {STATISTICS_EXTENSION} {default}")

        transfer.create_copy(spec, "source_tenant")
        built = postgres_cluster.psql(
            spec,
            f"CREATE EXTENSION {STATISTICS_EXTENSION} VERSION '{older}';"
            "CREATE SCHEMA statement_statistics;"
            "CREATE VIEW statement_statistics.current_database_statements AS"
            f" SELECT * FROM {STATISTICS_EXTENSION}(true)"
            " WHERE dbid = (SELECT oid FROM pg_database"
            " WHERE datname = current_database());",
            dbname="source_tenant",
        )
        assert built.returncode == 0, built.stderr

        dump = scratch / "source_tenant.dump"
        source_dsn = postgres_cluster.dsn(spec, "source_tenant")
        transfer.dump_database(spec, source_dsn, dump)

        # Unpinned is the reported failure: the dump installs the cluster
        # default, and the view's positional alias list resolves a name twice.
        transfer.create_copy(spec, "unpinned_copy")
        with pytest.raises(RuntimeError, match="is ambiguous"):
            transfer.restore_copy(spec, "unpinned_copy", dump)

        pins = extensions.extension_pins(
            spec, extensions.source_extensions(source_dsn)
        )
        assert [(pin.name, pin.version) for pin in pins] == [
            (STATISTICS_EXTENSION, older),
        ]

        transfer.create_copy(spec, "pinned_copy")
        extensions.pin_extension_versions(spec, "pinned_copy", pins)
        transfer.restore_copy(spec, "pinned_copy", dump)

        restored = postgres_cluster.psql(
            spec,
            "SELECT e.extversion, to_regclass("
            "'statement_statistics.current_database_statements') IS NOT NULL "
            "FROM pg_extension e "
            f"WHERE e.extname = '{STATISTICS_EXTENSION}'",
            dbname="pinned_copy",
        )
        assert restored.stdout.strip() == f"{older}|t"
    finally:
        postgres_cluster.destroy(spec)
        shutil.rmtree(scratch, ignore_errors=True)
