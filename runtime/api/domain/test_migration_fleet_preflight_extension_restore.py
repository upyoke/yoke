"""The real dump/restore round trip the fleet preflight failed on.

Built on a scratch cluster, at the shape the fleet actually runs: the
statistics extension in a schema of its own, a function returning ``SETOF``
that extension's view, and a view over the function. Restoring that into a
database whose extension version differs fails outright, so the round trip is
run twice — once unpinned to watch it fail, once staged to watch it survive.

This needs real Postgres *server* binaries, which is why it resolves them
rather than trusting ``PATH``: Debian wraps the client tools into ``PATH`` but
not ``initdb``, so a runner with a complete install still has to be asked for
its versioned directory. Where the environment says it is CI, a missing
prerequisite fails instead of skipping — a round trip that quietly does not
run is how the unrestorable copy reached a release in the first place.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

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

#: Debian keeps every server binary here, one directory per major version.
VERSIONED_BIN_GLOB = "/usr/lib/postgresql/*/bin"


def _unavailable(reason: str) -> None:
    """Skip locally, fail on CI. A skip there proves nothing and reads green."""
    if os.environ.get("CI"):
        pytest.fail(f"this round trip must run on CI: {reason}")
    pytest.skip(reason)


def _server_bin_dir() -> Tuple[Optional[Path], List[str]]:
    """The directory holding ``initdb``, plus the places that were tried."""
    searched: List[str] = []

    on_path = shutil.which("initdb")
    if on_path:
        return Path(on_path).parent, searched
    searched.append("PATH")

    if shutil.which("pg_config"):
        probe = subprocess.run(
            ["pg_config", "--bindir"], capture_output=True, text=True, timeout=30
        )
        candidate = Path(probe.stdout.strip()) if probe.stdout.strip() else None
        if candidate is not None:
            searched.append(str(candidate))
            if (candidate / "initdb").exists():
                return candidate, searched
    else:
        searched.append("pg_config (absent)")

    versioned = sorted(Path("/").glob(VERSIONED_BIN_GLOB.lstrip("/")))
    searched.append(VERSIONED_BIN_GLOB)
    for candidate in reversed(versioned):
        if (candidate / "initdb").exists():
            return candidate, searched

    return None, searched


@pytest.fixture(scope="module")
def cluster():
    """A scratch cluster, rooted shallowly enough for a unix socket path.

    The root sits directly under the OS temp dir because socket paths cap near
    103 bytes and pytest's nested tmp_path blows that on macOS.
    """
    bin_dir, searched = _server_bin_dir()
    if bin_dir is None:
        _unavailable(
            "no Postgres server binaries (initdb) found; searched "
            + ", ".join(searched)
        )
    scratch = Path(tempfile.mkdtemp(prefix="yoke-extpin-", dir="/tmp"))
    spec = ClusterSpec(
        root=scratch,
        superuser="rehearsaluser",
        server_settings=(("fsync", "off"),),
        bin_dir=bin_dir,
        stop_mode="immediate",
    )
    try:
        assert postgres_cluster.ensure_started(spec) == 0
        yield spec
    finally:
        postgres_cluster.destroy(spec)
        shutil.rmtree(scratch, ignore_errors=True)


def _offered_versions(spec: ClusterSpec) -> Tuple[str, ...]:
    probe = postgres_cluster.psql(
        spec,
        "SELECT version FROM pg_available_extension_versions "
        f"WHERE name = '{STATISTICS_EXTENSION}'",
    )
    return tuple(line.strip() for line in probe.stdout.splitlines() if line.strip())


def _ordered(version: str) -> tuple:
    return tuple(int(part) for part in version.split("."))


@pytest.fixture(scope="module")
def older_version(cluster) -> str:
    """A version the cluster can install but would not choose on its own."""
    default = postgres_cluster.psql(
        cluster,
        "SELECT default_version FROM pg_available_extensions "
        f"WHERE name = '{STATISTICS_EXTENSION}'",
    ).stdout.strip()
    if not default:
        _unavailable(
            f"{STATISTICS_EXTENSION} is not available on this cluster; the "
            "contrib modules for its Postgres build are not installed"
        )
    older = sorted(
        (v for v in _offered_versions(cluster) if _ordered(v) < _ordered(default)),
        key=_ordered,
    )
    if not older:
        _unavailable(
            f"this cluster offers only {STATISTICS_EXTENSION} {default}, so no "
            "version shift can be staged"
        )
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


def _view_column_count(spec: ClusterSpec, database: str) -> str:
    return postgres_cluster.psql(
        spec,
        "SELECT count(*) FROM information_schema.columns"
        f" WHERE table_schema = '{EXTENSION_SCHEMA}'"
        f" AND table_name = 'current_database_statements'",
        dbname=database,
    ).stdout.strip()


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

    # The staged extension must give the view the source's rowtype, not the
    # cluster default's wider one — which is the whole point of pinning.
    assert _view_column_count(spec, "pinned_copy") == _view_column_count(
        spec, "source_tenant"
    )
