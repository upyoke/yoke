"""A function declared side-effect-free must not change the database's schema.

Several read helpers used to call an ``ensure_schema`` helper at the top of
their own body so that a minimal database with no boot converge behind it still
worked. On a live universe that meant a dispatch the registry declares
``side_effects=[]`` executed DDL and committed -- ``CREATE TABLE IF NOT
EXISTS`` in most cases, and an ``ALTER TABLE ... ADD COLUMN`` in the onboarding
run reader. The schema owner is
:func:`yoke_core.domain.schema_init.converge_core_schema`, which creates every
one of those tables on boot, so the calls were redundant as well as wrong.

Two halves, because neither alone covers the property:

``test_read_paths_execute_no_ddl`` is the runtime half, and it is narrow. It
drives the repaired entrypoints through a connection that refuses DDL. The
general runtime form -- every ``side_effects=[]`` function in the registry
proved DDL-free by dispatching it -- is not writable, because it would need a
valid payload, target and actor for each one.

``test_schema_helper_call_sites_match_allowlist`` is the static half, and it is
the general one. It holds repo-wide: every call to a schema-creating helper
anywhere in the serving package has to appear in an allowlist naming why it is
legitimate. A new read path that calls one fails this test with the call site
named. The allowlist also records the remaining write-path callers, which are
not the defect this module pins but are the same pattern.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Iterator

import pytest

from yoke_core.domain import machine_qa_capability, project_onboarding_runs
from yoke_core.domain import strategize_carry_state
from yoke_core.domain.project_onboarding_runs import ProjectOnboardingRunError

#: First words that make a statement a schema change rather than a query.
_DDL_VERBS = frozenset({"create", "alter", "drop", "truncate", "rename", "comment"})

#: A helper that creates or alters tables. Name-shaped rather than an explicit
#: list so a newly added helper is covered the moment it follows the
#: convention every existing one follows.
_SCHEMA_HELPER_NAME = re.compile(
    r"^_?(ensure_schema|ensure_\w*_schema|create_\w*_tables|ensure_\w*_tables)$"
)

_SERVING_PACKAGE = Path(__file__).resolve().parents[3] / (
    "packages/yoke-core/src/yoke_core"
)

#: Every sanctioned call to a schema-creating helper in the serving package,
#: as ``relative/path.py::enclosing_function``. Not one of these is reachable
#: from a function the registry declares ``side_effects=[]``, which is the
#: property this list exists to keep true.
_SANCTIONED_SCHEMA_HELPER_CALLS: frozenset[str] = frozenset(
    {
        # The boot converge and the modules it delegates to. This is the
        # schema owner: a container converges before it serves, and a
        # machine-local universe converges once per process before dispatch.
        "api/server_entrypoint.py::ensure_permission_catalog",
        "api/server_entrypoint.py::main",
        "domain/schema_init.py::converge_core_schema",
        "domain/schema_init_tables.py::create_core_tables",
        "domain/schema_init_actor_path_claim_tables.py::create_actor_path_claim_tables",
        "domain/schema_init_path_tables.py::create_path_registry_tables",
        "domain/session_control_schema.py::create_session_control_tables",
        "domain/auth_schema.py::create_auth_tables",
        "domain/events_schema.py::_create_events_table",
        "domain/pack_projection.py::converge_pack_catalog",
        "domain/flow_init.py::converge_flow_catalog",
        "domain/flow_init.py::_ensure_flow_schema",
        "domain/workflow_schema.py::ensure_workflow_schema",
        # Ordered migration history, which changes schema by definition.
        "domain/migrations/0015_session_surface_and_organization_domain.py::apply",
        "domain/migrations/0021_session_termination.py::apply",
        # ``cmd_init`` surfaces whose whole job is standing a database up.
        "domain/events_schema.py::cmd_init",
        "domain/flow_init.py::cmd_init",
        "domain/project_structure.py::cmd_init",
        "domain/projects_restart.py::cmd_init",
        # One schema helper calling another.
        "domain/project_onboarding_runs.py::ensure_schema",
        "domain/project_snapshot_chunk_uploads.py::_ensure_chunk_tables",
        # Recorded, not endorsed: write paths that converge their own table
        # before writing it. A write may change rows; converging schema is the
        # same pattern as the read defect this module pins and wants removing
        # too. Out of scope here because the invariant is about declared
        # reads, and none of these is reachable from one.
        "domain/harness_machine_state.py::upsert_harness_machine_reports",
        "domain/machine_operation_recording.py::record_test_machine_operation",
        "domain/machine_qa_capability_settings.py::replace_test_machine_settings",
        "domain/machine_verification_recording.py::record_test_machine_verification",
        "domain/ouroboros_entry_corrections.py::record_correction",
        "domain/project_snapshot_chunk_uploads.py::sync_chunk",
        "domain/sessions_offer_lane.py::emit_lane_override_applied_event",
    }
)


class SchemaChangeInReadPath(AssertionError):
    """A read path executed DDL. Raised by the refusing connection below."""


def _statements(sql: str) -> Iterator[str]:
    """Yield each statement in *sql* with comments and blank lines removed."""
    for chunk in str(sql).split(";"):
        lines = [
            line.strip()
            for line in chunk.splitlines()
            if line.strip() and not line.strip().startswith("--")
        ]
        if lines:
            yield " ".join(lines)


def _refuse_ddl(sql: str) -> None:
    for statement in _statements(sql):
        verb = statement.split(None, 1)[0].lower()
        if verb in _DDL_VERBS:
            raise SchemaChangeInReadPath(
                f"a read path executed DDL: {statement[:120]!r}. The schema owner "
                "is schema_init.converge_core_schema, which creates these tables "
                "on boot; remove the ensure_schema call from this path rather "
                "than converging from a function the registry declares "
                "side_effects=[]."
            )


class _DDLRefusingConnection:
    """Pass-through connection that raises on any schema-changing statement."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def execute(self, sql: str, params: Any = None) -> Any:
        _refuse_ddl(sql)
        if params is None:
            return self._conn.execute(sql)
        return self._conn.execute(sql, params)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def _build_fixture_schema(conn: Any) -> None:
    """Create the tables the boot converge would, the way a fixture must.

    ``test_db`` applies a hand-composed fixture schema and deliberately never
    runs ``converge_core_schema``, so these tables are absent from it. Calling
    the helpers here is their whole remaining purpose, and it sets the test up
    to prove the interesting thing: that the readers below do not call them.
    """
    from yoke_core.domain.machine_verification_schema import (
        ensure_test_machine_schema,
    )
    from yoke_core.domain.strategize_carry_schema import (
        ensure_schema as ensure_carry_schema,
    )

    ensure_carry_schema(conn)
    project_onboarding_runs.ensure_schema(conn)
    ensure_test_machine_schema(conn)


def _seed_project(conn: Any, *, slug: str = "yoke") -> int:
    row = conn.execute(
        "SELECT id FROM projects WHERE slug = %s", (slug,)
    ).fetchone()
    if row is not None:
        return int(row[0] if not hasattr(row, "keys") else row["id"])
    conn.execute(
        "INSERT INTO projects (slug, name, public_item_prefix, created_at) "
        "VALUES (%s, %s, %s, '2026-01-01T00:00:00Z')",
        (slug, slug.title(), "YOK"),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM projects WHERE slug = %s", (slug,)
    ).fetchone()
    return int(row[0] if not hasattr(row, "keys") else row["id"])


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE IF NOT EXISTS t (id INTEGER)",
        "ALTER TABLE t ADD COLUMN note TEXT",
        "CREATE INDEX IF NOT EXISTS idx_t ON t(id)",
        "-- leading comment\nCREATE TABLE t (id INTEGER)",
        "SELECT 1;\nCREATE TABLE t (id INTEGER)",
    ],
)
def test_refusing_connection_detects_ddl(sql):
    """The detector fires, so the absence-of-raise tests below mean something.

    Includes a trailing statement in a multi-statement script and a leading
    comment, because a detector that only inspected the first word of the
    whole string would pass both of those while missing the DDL.
    """
    with pytest.raises(SchemaChangeInReadPath):
        _refuse_ddl(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "INSERT INTO t (id) VALUES (1)",
        "UPDATE t SET note = 'x'",
        "DELETE FROM t WHERE id = 1",
        "WITH c AS (SELECT 1) SELECT * FROM c",
    ],
)
def test_refusing_connection_allows_queries_and_row_writes(sql):
    """Row reads and row writes pass; only schema changes are refused."""
    _refuse_ddl(sql)


def test_read_paths_execute_no_ddl(test_db):
    """The repaired readers run against a DDL-refusing connection.

    Each of these is reached from a function registered ``side_effects=[]``:
    ``strategy.carry.candidate_set`` and ``strategy.carry.summary``,
    ``onboard.checklist`` run reads, and ``test_machine.get`` /
    ``test_machine.list``. The assertion is the absence of a raise.
    """
    _seed_project(test_db)
    _build_fixture_schema(test_db)
    conn = _DDLRefusingConnection(test_db)

    strategize_carry_state.get_candidate_set(conn, "yoke")
    machine_qa_capability.test_machine_list(conn, project="yoke")

    # get_run reaches its SELECT without converging first; a missing run is
    # the domain refusal, which proves the DDL step is gone.
    with pytest.raises(ProjectOnboardingRunError):
        project_onboarding_runs.get_run("run-absent", conn=conn)


def test_write_paths_in_repaired_modules_execute_no_ddl(test_db):
    """The writers beside those readers were repaired in the same pass.

    They sat in the same functions, and leaving them would have left the
    static allowlist below unable to distinguish a read from a write in these
    modules. A write may change rows; it still has no business converging.
    """
    _seed_project(test_db)
    _build_fixture_schema(test_db)
    conn = _DDLRefusingConnection(test_db)

    strategize_carry_state.register_new_landings(conn, "yoke")
    strategize_carry_state.mark_items(conn, "yoke", [], "reflected")


def _schema_helper_call_sites() -> dict[str, list[int]]:
    """Return ``path::function`` -> line numbers for every helper call."""
    found: dict[str, list[int]] = {}
    for path in sorted(_SERVING_PACKAGE.rglob("*.py")):
        relative = path.relative_to(_SERVING_PACKAGE).as_posix()
        if relative.startswith("install_bundle_tree/"):
            # Packaged Pack snapshots are shipped bytes, not serving code.
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for scope in ast.walk(tree):
            if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(scope):
                if not isinstance(node, ast.Call):
                    continue
                name = _called_name(node.func)
                if name is None or not _SCHEMA_HELPER_NAME.match(name):
                    continue
                if name == scope.name:
                    # A helper's own recursive/def-site name, not a caller.
                    continue
                key = f"{relative}::{scope.name}"
                found.setdefault(key, []).append(node.lineno)
    return found


def _called_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def test_schema_helper_call_sites_match_allowlist():
    """No serving function may call a schema-creating helper unsanctioned.

    This is the general half. It does not care which dispatch reaches the
    call; it pins the complete set of places DDL can originate, so a read path
    cannot quietly acquire one again.
    """
    found = _schema_helper_call_sites()
    unsanctioned = sorted(set(found) - _SANCTIONED_SCHEMA_HELPER_CALLS)
    stale = sorted(_SANCTIONED_SCHEMA_HELPER_CALLS - set(found))

    assert not unsanctioned, (
        "these functions call a schema-creating helper and are not in the "
        "allowlist: "
        + ", ".join(f"{key} (line {found[key][0]})" for key in unsanctioned)
        + ". A read must not converge schema -- the boot converge owns it. If "
        "the call is legitimate (the converge itself, a cmd_init surface, or "
        "one schema helper calling another), add it to "
        "_SANCTIONED_SCHEMA_HELPER_CALLS with the reason."
    )
    assert not stale, (
        "these allowlist entries no longer call a schema helper and should be "
        "removed: " + ", ".join(stale)
    )
