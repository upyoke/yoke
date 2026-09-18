"""The real dump/restore round trip the fleet preflight failed on.

Built on a scratch cluster, at the shape the fleet actually runs: the
statistics extension in a schema of its own, a function returning ``SETOF``
that extension's view, and a view over the function. Restoring that into a
database whose extension version differs fails outright, so the round trip is
run twice — once unpinned to watch it fail, once staged to watch it survive.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from yoke_core.domain import (
    migration_fleet_preflight_extensions as extensions,
    migration_fleet_preflight_transfer as transfer,
    postgres_cluster,
)
from yoke_core.domain.postgres_cluster import ClusterSpec

STATISTICS_EXTENSION = "pg_stat_statements"

#: Where prod and stage keep the extension, and the objects that depend on it.
EXTENSION_SCHEMA = "statement_statistics"
READER_FUNCTION = f"{EXTENSION_SCHEMA}.current_database_statements_read"
DEPENDENT_VIEW = f"{EXTENSION_SCHEMA}.current_database_statements"


def _ordered(version: str) -> tuple:
    return tuple(int(part) for part in version.split("."))


def _offered_versions(spec: ClusterSpec) -> tuple:
    probe = postgres_cluster.psql(
        spec,
        "SELECT version FROM pg_available_extension_versions "
        f"WHERE name = '{STATISTICS_EXTENSION}'",
    )
    return tuple(line.strip() for line in probe.stdout.splitlines() if line.strip())


@pytest.fixture(scope="module")
def cluster():
    """A scratch cluster, rooted shallowly enough for a unix socket path.

    The root sits directly under the OS temp dir because socket paths cap near
    103 bytes and pytest's nested tmp_path blows that on macOS.
    """
    if shutil.which("initdb") is None:
        pytest.skip("system Postgres binaries not on PATH")
    scratch = Path(tempfile.mkdtemp(prefix="yoke-extpin-", dir="/tmp"))
    spec = ClusterSpec(
        root=scratch,
        superuser="rehearsaluser",
        # Preloaded so the restored view can actually be read; the extension
        # installs either way, but querying it needs the shared library.
        server_settings=(
            ("fsync", "off"),
            ("shared_preload_libraries", STATISTICS_EXTENSION),
        ),
        stop_mode="immediate",
    )
    try:
        assert postgres_cluster.ensure_started(spec) == 0
        yield spec
    finally:
        postgres_cluster.destroy(spec)
        shutil.rmtree(scratch, ignore_errors=True)


@pytest.fixture(scope="module")
def older_version(cluster) -> str:
    """A version the cluster can install but would not choose on its own."""
    default = postgres_cluster.psql(
        cluster,
        "SELECT default_version FROM pg_available_extensions "
        f"WHERE name = '{STATISTICS_EXTENSION}'",
    ).stdout.strip()
    if not default:
        pytest.skip(f"{STATISTICS_EXTENSION} is not available on this cluster")
    older = sorted(
        (v for v in _offered_versions(cluster) if _ordered(v) < _ordered(default)),
        key=_ordered,
    )
    if not older:
        pytest.skip(f"this cluster offers only {STATISTICS_EXTENSION} {default}")
    return older[-1]


def _build_source(spec: ClusterSpec, database: str, version: str) -> None:
    """The tenant shape: extension, a reader over it, and a view over that.

    The view is what breaks. ``pg_dump`` renders it with a positional column
    alias list taken from the reader's rowtype, which is the extension's view
    rowtype — so a wider extension version shifts the list and one column name
    resolves twice.
    """
    transfer.create_copy(spec, database)
    built = postgres_cluster.psql(
        spec,
        f"CREATE SCHEMA {EXTENSION_SCHEMA};"
        f"CREATE EXTENSION {STATISTICS_EXTENSION}"
        f" WITH SCHEMA {EXTENSION_SCHEMA} VERSION '{version}';"
        f"CREATE FUNCTION {READER_FUNCTION}()"
        f" RETURNS SETOF {EXTENSION_SCHEMA}.{STATISTICS_EXTENSION}"
        " LANGUAGE sql AS $$"
        f" SELECT * FROM {EXTENSION_SCHEMA}.{STATISTICS_EXTENSION}"
        " WHERE dbid = (SELECT oid FROM pg_database"
        " WHERE datname = current_database()) $$;"
        f"CREATE VIEW {DEPENDENT_VIEW} AS SELECT * FROM {READER_FUNCTION}();",
        dbname=database,
    )
    assert built.returncode == 0, built.stderr


def test_a_view_over_the_extension_rowtype_restores_at_the_source_version(
    cluster, older_version,
) -> None:
    spec = cluster
    _build_source(spec, "source_tenant", older_version)
    dump = spec.root / "source_tenant.dump"
    source_dsn = postgres_cluster.dsn(spec, "source_tenant")
    transfer.dump_database(spec, source_dsn, dump)

    # Unpinned is the reported failure: the dump installs the cluster default
    # and the view's alias list resolves a name twice.
    transfer.create_copy(spec, "unpinned_copy")
    with pytest.raises(RuntimeError, match="is ambiguous"):
        transfer.restore_copy(spec, "unpinned_copy", dump)

    pins = extensions.extension_pins(spec, extensions.source_extensions(source_dsn))
    assert [(pin.name, pin.version, pin.schema) for pin in pins] == [
        (STATISTICS_EXTENSION, older_version, EXTENSION_SCHEMA),
    ]

    transfer.create_copy(spec, "pinned_copy")
    use_list = extensions.stage_pinned_extensions(
        spec,
        "pinned_copy",
        pins,
        dump=dump,
        list_path=spec.root / "source_tenant.restore-list",
    )
    # The schema is staged, so the dump's own CREATE SCHEMA has to be skipped.
    assert use_list is not None
    transfer.restore_copy(spec, "pinned_copy", dump, use_list=use_list)

    restored = postgres_cluster.psql(
        spec,
        "SELECT e.extversion, n.nspname,"
        f" to_regclass('{DEPENDENT_VIEW}') IS NOT NULL,"
        f" to_regproc('{READER_FUNCTION}') IS NOT NULL"
        " FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace"
        f" WHERE e.extname = '{STATISTICS_EXTENSION}'",
        dbname="pinned_copy",
    )
    assert restored.stdout.strip() == f"{older_version}|{EXTENSION_SCHEMA}|t|t"

    # The staged schema must hold the dump's objects, not shadow them: reading
    # the view proves the restored definition binds to the pinned extension.
    readable = postgres_cluster.psql(
        spec, f"SELECT count(*) >= 0 FROM {DEPENDENT_VIEW}", dbname="pinned_copy",
    )
    assert readable.returncode == 0, readable.stderr
    assert readable.stdout.strip() == "t"
