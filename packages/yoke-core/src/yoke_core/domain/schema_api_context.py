"""Generate role/topic-scoped schema/API context packets for Yoke agents.

The renderer expands canonical packet markers from live schema and command
probes reconciled against the curated seed. The module CLI renders one topic,
one role, or checks the complete packet corpus for drift and size limits.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional

from yoke_core.domain import schema_api_context_seed as seed
from yoke_core.domain.schema_api_context_render import (
    render_command_block,
    render_function_call_surface_block,
    render_invariant_block,
    render_item_entry_surface_block,
    render_json_nested_schema_block,
    render_package_roots_block,
    render_table_block,
)
from yoke_core.domain.schema_common import (
    _get_columns_with_types,
)


# ---------------------------------------------------------------------------
# Live introspection
# ---------------------------------------------------------------------------


LIVE_SCHEMA_CONNECT_TIMEOUT_ENV = "YOKE_SCHEMA_API_CONTEXT_CONNECT_TIMEOUT_SECONDS"
_LIVE_SCHEMA_CACHE: dict[str, Optional[list[tuple[str, str]]]] = {}
_LIVE_SCHEMA_UNAVAILABLE = False


def _live_schema_connect_timeout() -> int:
    raw = os.environ.get(LIVE_SCHEMA_CONNECT_TIMEOUT_ENV, "1").strip()
    try:
        parsed = int(raw)
    except ValueError:
        return 1
    return max(1, parsed)


def _connect_live_schema():
    """Open a short advisory schema-probe connection.

    Packet rendering must never wedge behind connected-env self-heal. Live
    schema is only a drift aid here; stateful DB readers still use the normal
    ``db_helpers`` / readiness connection path.
    """
    import psycopg

    from yoke_contracts.control_plane_locality import local_authority_exempt
    from yoke_core.domain import db_backend

    # Declared exempt because probing IS the question: the caller treats any
    # failure as "no live schema" and renders from the seed instead. A machine
    # whose control plane is remote has no database to probe, which is one
    # more way for the probe to come back empty.
    with local_authority_exempt():
        return psycopg.connect(
            db_backend.resolve_pg_dsn(),
            autocommit=True,
            connect_timeout=_live_schema_connect_timeout(),
        )


def _try_live_schema(table: str) -> Optional[list[tuple[str, str]]]:
    """Return ``[(name, type), ...]`` for *table* or None if unavailable."""
    global _LIVE_SCHEMA_UNAVAILABLE
    if table in _LIVE_SCHEMA_CACHE:
        return _LIVE_SCHEMA_CACHE[table]
    if _LIVE_SCHEMA_UNAVAILABLE:
        return None
    try:
        conn = _connect_live_schema()
    except Exception:
        _LIVE_SCHEMA_UNAVAILABLE = True
        return None
    try:
        rows = _get_columns_with_types(conn, table)
    except Exception:
        rows = []
    finally:
        conn.close()
    resolved = rows or None
    _LIVE_SCHEMA_CACHE[table] = resolved
    return resolved


_TYPE_CLASSES = {
    "int": {"integer", "int", "bigint", "smallint", "int2", "int4", "int8"},
    "text": {"text", "varchar", "character varying", "char", "character", "clob"},
    "real": {
        "real",
        "double precision",
        "double",
        "float",
        "float4",
        "float8",
        "numeric",
        "decimal",
    },
    "blob": {"blob", "bytea"},
    "bool": {"boolean", "bool"},
    "timestamp": {
        "timestamp",
        "timestamptz",
        "timestamp without time zone",
        "timestamp with time zone",
        "date",
        "time",
    },
}
_TYPE_CLASS_BY_NAME = {
    name: klass for klass, names in _TYPE_CLASSES.items() for name in names
}


def _normalize_type(declared: str) -> str:
    """Collapse a column type to a dialect-independent class for drift comparison.

    The curated seed and live Postgres catalog may spell equivalent types
    differently. Comparing the coarse class (``int`` / ``text`` / ``real`` /
    ...) means dialect spelling and identity-PK widening are not flagged as
    drift, while a genuine class change (int vs text) still is. Unknown types
    compare by their lowercased base name verbatim.
    """
    base = (declared or "").strip().lower().split("(", 1)[0].strip()
    return _TYPE_CLASS_BY_NAME.get(base, base)


def _resolve_columns(table: str) -> list[tuple[str, str]]:
    """Reconcile live schema with curated seed.

    Returns the live columns when available, falling back to the seed
    when the live DB is unavailable. Raises ``DriftError`` when both are
    available and live disagrees with the seed on a column name/type
    that the seed declares — operator must update the seed rather than
    silently shipping a stale agent context.

    Under pytest, when the live schema looks like a fixture stub with
    missing seed columns, fall back to the seed silently — an earlier test
    pinned ``YOKE_DB`` at a minimal helper DB and unrelated rendering
    shouldn't fail downstream of leaked state. Real production schemas
    always carry the full column set; partial fixture tables don't.
    """
    seed_entry = seed.CANONICAL_TABLES.get(table)
    if seed_entry is None:
        raise KeyError(f"unknown table: {table}")
    seed_cols: list[tuple[str, str]] = list(seed_entry["columns"])
    live = _try_live_schema(table)
    if live is None:
        return seed_cols
    live_map = {n: t for (n, t) in live}
    missing_names = [name for name, _ in seed_cols if live_map.get(name) is None]
    drift: list[str] = []
    for name, declared in seed_cols:
        live_type = live_map.get(name)
        if live_type is None:
            drift.append(
                f"seed declares column {table}.{name} but live schema has no such column"
            )
        elif _normalize_type(live_type) != _normalize_type(declared):
            drift.append(
                f"seed declares {table}.{name} as {declared} but live schema has {live_type}"
            )
    if drift:
        if _running_under_pytest() and missing_names:
            return seed_cols
        raise DriftError("\n".join(drift))
    return seed_cols


class DriftError(RuntimeError):
    """Raised when the curated seed disagrees with the live schema."""


def _running_under_pytest() -> bool:
    return bool(
        os.environ.get("PYTEST_CURRENT_TEST")
        or os.environ.get("PYTEST_VERSION")
        or os.environ.get("PYTEST_XDIST_WORKER")
        or "pytest" in sys.modules
    )


# ---------------------------------------------------------------------------
# Live command surface introspection
# ---------------------------------------------------------------------------


def _try_help(module: str) -> Optional[str]:
    """Return ``<current-python> -m <module> --help`` output or None.

    Some Yoke CLIs (notably :mod:`yoke_core.hooks.sessions_cli`)
    print a custom usage banner and exit non-zero. Accept those banners,
    but reject interpreter/bootstrap errors instead of treating stderr as
    a live command surface.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", module, "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    combined = (result.stdout or "") + (result.stderr or "")
    if not combined.strip():
        return None
    if result.returncode != 0 and "usage:" not in combined.casefold():
        return None
    return combined


def has_command(module: str, fragment: str) -> bool:
    """Return True if *fragment* appears in ``--help`` for *module*."""
    text = _try_help(module)
    if text is None:
        return False
    return fragment in text


# ---------------------------------------------------------------------------
# Packet rendering
# ---------------------------------------------------------------------------


_TOPIC_HEADERS = {
    "core": "DB Quick Reference — core (control plane + structured fields)",
    "claims": "DB Quick Reference — claims (sessions, work, paths)",
    "auth": "DB Quick Reference — auth (roles, permissions, org/project grants)",
    "qa": "DB Quick Reference — qa (requirements, runs, gate preview)",
    "packs": "DB Quick Reference — packs (catalog and receipt projection)",
    "project": "DB Quick Reference — project (test commands, project_structure)",
}


def render_topic_packet(topic: str, *, role: str = "main_agent") -> str:
    """Return the role-aware markdown body for a single topic packet.

    The body is what lives between the marker pair in the canonical
    agent prompts. Caller wraps with ``agents_render_context`` if marker
    framing is desired.
    """
    if topic not in seed.TOPICS:
        raise ValueError(f"unknown topic: {topic}")
    if role not in seed.ROLE_TOPICS:
        raise ValueError(f"unknown role: {role}")
    header = _TOPIC_HEADERS[topic]
    parts: list[str] = [f"### {header}", ""]
    if topic == "core":
        parts.extend(render_invariant_block())
        parts.append("")
        parts.extend(render_package_roots_block())
        parts.append("")
        parts.extend(render_item_entry_surface_block())
        parts.append("")
        parts.extend(render_function_call_surface_block())
        parts.append("")
    parts.extend(render_command_block(topic, role=role))
    parts.append("")
    parts.extend(render_table_block(topic, _resolve_columns))
    json_block = render_json_nested_schema_block(topic)
    if json_block:
        parts.append("")
        parts.extend(json_block)
    return "\n".join(parts).rstrip() + "\n"


def render_role_packet(role: str) -> str:
    """Return the concatenated packet body for *role*'s assigned topics."""
    if role not in seed.ROLE_TOPICS:
        raise ValueError(f"unknown role: {role}")
    chunks = [render_topic_packet(t, role=role) for t in seed.ROLE_TOPICS[role]]
    if role == "main_agent":
        chunks[-1] = (
            chunks[-1].rstrip()
            + "\n"
            + (
                "**Deployment-run raw-query hint:** "
                "`deployment_flows.target_environment_id` references "
                "`environments.id` (JOIN environments for the display name; "
                "`target_tier` is persistent/ephemeral/NULL — there is no "
                "`target_env` column); `deployment_runs.status` and "
                "`deployment_runs.current_stage` record progress. There is no "
                "`deployment_runs.item_id`; join through `deployment_run_items` "
                "for item-bound runs."
            )
        )
    return "\n".join(chunks).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Drift / size checks
# ---------------------------------------------------------------------------


def detect_seed_drift() -> list[str]:
    """Return list of seed/live divergences, or [] when the seed agrees."""
    drift: list[str] = []
    for table in seed.CANONICAL_TABLES:
        try:
            _resolve_columns(table)
        except DriftError as exc:
            drift.append(str(exc))
    return drift


def check_role_packet_size(role: str) -> tuple[int, int]:
    """Return ``(line_count, budget)`` for the role's packet."""
    body = render_role_packet(role)
    return (body.count("\n"), seed.PACKET_LINE_BUDGET_PER_ROLE)


def check_aggregate_size() -> tuple[int, int]:
    """Return ``(total_line_count, aggregate_budget)`` across all roles."""
    total = sum(render_role_packet(r).count("\n") for r in seed.ROLE_TOPICS)
    return (total, seed.PACKET_LINE_BUDGET_AGGREGATE)


def main(argv: Optional[list[str]] = None) -> int:
    from yoke_core.domain.schema_api_context_cli import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":
    import sys

    sys.exit(main())
