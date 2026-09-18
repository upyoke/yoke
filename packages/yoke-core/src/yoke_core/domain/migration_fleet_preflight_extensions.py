"""Give a rehearsal copy the extension versions its source actually runs.

A copy is only evidence while it is the same database. ``pg_dump`` names its
extensions without versions — ``CREATE EXTENSION IF NOT EXISTS <name> WITH
SCHEMA <schema>`` — deliberately, so a dump stays portable across builds. The
cost is that a restore installs whatever version the *receiving* cluster
defaults to, so a rehearsal cluster one Postgres release ahead of the fleet
converges a copy running extension code the tenant has never run.

It is worse than a silent difference, because objects compiled against the
source's row types may not restore at all. ``pg_get_viewdef`` renders a view
over a set-returning extension function with a positional column alias list::

    FROM pg_stat_statements(true) pg_stat_statements(userid, dbid, ..., wal_bytes)

A newer extension version returns more columns, and inserts some of them
mid-list. Postgres applies the shorter alias list positionally and lets the
surplus columns keep their own names, so one name can end up resolving twice
in the same range table entry and ``CREATE VIEW`` fails as ambiguous — naming
a column the view selects, which reads like a corrupt dump rather than an
extension-version mismatch.

So the source's versions are read before anything is copied, and pinned into
the fresh database before the restore runs. A version this cluster cannot
install refuses while refusing is still free, rather than producing a copy
that quietly is not the tenant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Sequence, Tuple

from yoke_core.domain import postgres_cluster
from yoke_core.domain.postgres_cluster import ClusterSpec

#: Schemas a freshly created database already has. A pin may only target one
#: of these: ``pg_dump`` emits ``CREATE SCHEMA`` for every schema it had to
#: create, so pre-creating any other one makes the restore fail as a duplicate.
PINNABLE_SCHEMAS: FrozenSet[str] = frozenset(
    {"public", "pg_catalog", "information_schema"}
)

SOURCE_EXTENSIONS_SQL = """
SELECT extension.extname, extension.extversion, namespace.nspname
FROM pg_extension AS extension
JOIN pg_namespace AS namespace ON namespace.oid = extension.extnamespace
ORDER BY extension.extname
"""

AVAILABLE_EXTENSIONS_SQL = """
SELECT available.name, available.default_version, offered.version
FROM pg_available_extensions AS available
JOIN pg_available_extension_versions AS offered ON offered.name = available.name
"""


class CopyFidelityError(RuntimeError):
    """The rehearsal cluster cannot reproduce the source's extensions."""


@dataclass(frozen=True)
class SourceExtension:
    """One extension as the live source has it installed."""

    name: str
    version: str
    schema: str


@dataclass(frozen=True)
class ClusterExtensions:
    """What the rehearsal cluster can install, and what it defaults to."""

    server_version: str
    default_versions: Dict[str, str]
    offered_versions: FrozenSet[Tuple[str, str]]

    def offers(self, extension: "SourceExtension") -> bool:
        return (extension.name, extension.version) in self.offered_versions

    def offered_for(self, name: str) -> Tuple[str, ...]:
        """Every version of *name* this cluster could install, for a refusal."""
        return tuple(
            sorted(
                version
                for offered, version in self.offered_versions
                if offered == name
            )
        )


def source_extensions(source_dsn: str) -> Tuple[SourceExtension, ...]:
    """Read every extension the live source has, with its version and schema."""
    from yoke_core.domain import db_backend

    conn = db_backend.connect_psycopg(source_dsn)
    try:
        rows = conn.execute(SOURCE_EXTENSIONS_SQL).fetchall()
    finally:
        conn.close()
    return tuple(
        SourceExtension(str(row[0]), str(row[1]), str(row[2])) for row in rows
    )


def cluster_extensions(spec: ClusterSpec) -> ClusterExtensions:
    """Read what the rehearsal cluster offers, from the cluster itself."""
    from yoke_core.domain import db_backend

    conn = db_backend._open_native_postgres(postgres_cluster.dsn(spec))
    try:
        server_version = str(conn.execute("SHOW server_version").fetchone()[0])
        rows = conn.execute(AVAILABLE_EXTENSIONS_SQL).fetchall()
    finally:
        conn.close()
    return ClusterExtensions(
        server_version=server_version,
        default_versions={str(row[0]): str(row[1]) for row in rows},
        offered_versions=frozenset((str(row[0]), str(row[2])) for row in rows),
    )


def extension_pins(
    spec: ClusterSpec,
    extensions: Sequence[SourceExtension],
) -> Tuple[SourceExtension, ...]:
    """The source extensions a restore would otherwise install wrong.

    An extension this cluster already defaults to the source's version needs
    no pin: the dump's own statement produces it. Everything else is pinned.
    """
    catalog = cluster_extensions(spec)
    pins: List[SourceExtension] = []
    for extension in extensions:
        if catalog.default_versions.get(extension.name) == extension.version:
            continue
        if not catalog.offers(extension):
            raise CopyFidelityError(_unavailable_version_refusal(extension, catalog))
        if extension.schema not in PINNABLE_SCHEMAS:
            raise CopyFidelityError(_unpinnable_schema_refusal(extension))
        pins.append(extension)
    return tuple(pins)


def _unavailable_version_refusal(
    extension: SourceExtension, catalog: ClusterExtensions,
) -> str:
    offered = ", ".join(catalog.offered_for(extension.name)) or "no version"
    instead = catalog.default_versions.get(extension.name, "nothing")
    return (
        f"the source installs {extension.name} {extension.version}, which this "
        f"rehearsal cluster (PostgreSQL {catalog.server_version}) cannot "
        f"install: it offers {offered}. Restoring would install {instead} "
        f"instead, so the copy would not be the database this rehearsal is "
        f"about. Install the contrib build that ships {extension.name} "
        f"{extension.version} for this cluster's PostgreSQL major version, or "
        f"rehearse this fleet from a machine whose engine offers it."
    )


def _unpinnable_schema_refusal(extension: SourceExtension) -> str:
    return (
        f"the source installs {extension.name} {extension.version} in schema "
        f"{extension.schema!r}, which the dump creates itself, so pinning the "
        f"version there would collide with the dump's own CREATE SCHEMA. "
        f"Pinning only reaches schemas every fresh database already has "
        f"({', '.join(sorted(PINNABLE_SCHEMAS))}). Relocate the extension on "
        f"the source (ALTER EXTENSION {extension.name} SET SCHEMA public), or "
        f"teach this module to stage the dump's schemas before it pins."
    )


def pin_extension_versions(
    spec: ClusterSpec,
    copy_name: str,
    pins: Sequence[SourceExtension],
) -> None:
    """Install the pinned extensions in the fresh copy, before the restore.

    The dump's ``CREATE EXTENSION IF NOT EXISTS`` then finds each one already
    present and becomes the no-op it reads as, leaving the source's version in
    place for every object the restore compiles against it.
    """
    if not pins:
        return
    from psycopg import sql

    from yoke_core.domain import db_backend

    conn = db_backend._open_native_postgres(
        postgres_cluster.dsn(spec, copy_name), autocommit=True
    )
    try:
        for extension in pins:
            conn.execute(
                sql.SQL("CREATE EXTENSION {} WITH SCHEMA {} VERSION {}").format(
                    sql.Identifier(extension.name),
                    sql.Identifier(extension.schema),
                    sql.Literal(extension.version),
                )
            )
    finally:
        conn.close()


__all__ = [
    "AVAILABLE_EXTENSIONS_SQL",
    "ClusterExtensions",
    "CopyFidelityError",
    "PINNABLE_SCHEMAS",
    "SOURCE_EXTENSIONS_SQL",
    "SourceExtension",
    "cluster_extensions",
    "extension_pins",
    "pin_extension_versions",
    "source_extensions",
]
