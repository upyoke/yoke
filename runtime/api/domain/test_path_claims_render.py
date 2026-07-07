"""Coverage for the ``## Path Claims`` body renderer."""

from __future__ import annotations


from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    SNAP,
    conn,
    local_human,
    seed_target,
)
from yoke_core.domain.path_claims import activate, register
from yoke_core.domain.path_claims_render import (
    PATH_CLAIMS_HEADING,
    render_path_claims_section,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _apply_core_only_schema() -> None:
    """``init_test_db`` strategy building a DB *without* the path tables.

    Simulates a minimal-fixture / pre-migration checkout: ``items`` and
    events present, ``path_claims`` absent. Resolves its connection
    through the backend factory so the renderer's fail-open swallow fires
    on whichever engine's missing-table error type the active backend
    raises.
    """
    from yoke_core.domain import db_backend
    from yoke_core.domain.events_schema import _create_events_table
    from yoke_core.domain.schema_init_tables import create_core_tables

    c = db_backend.connect()
    try:
        create_core_tables(c)
        c.execute(
            "INSERT INTO projects "
            "(id, slug, name, public_item_prefix, created_at) "
            "VALUES (1, 'yoke', 'Yoke', 'YOK', "
            "'2026-05-01T00:00:00Z') "
            "ON CONFLICT (id) DO NOTHING"
        )
        _create_events_table(c)
        c.commit()
    finally:
        c.close()


def _seed_item(conn, *, item_id: int) -> int:
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (item_id, item_id),
    )
    conn.commit()
    return item_id


class TestRenderPathClaimsSection:
    def test_returns_none_when_no_claims_attached(self, conn):
        item_id = _seed_item(conn, item_id=11001)
        assert render_path_claims_section(conn, item_id) is None

    def test_renders_planned_claim_with_paths(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=11002)
        ta = seed_target(conn, path_string="runtime/api/domain")
        tb = seed_target(conn, path_string="docs/path-claims.md")
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[ta, tb], item_id=item_id,
        )
        rendered = render_path_claims_section(conn, item_id)
        assert rendered is not None
        # Header
        assert rendered.startswith(PATH_CLAIMS_HEADING)
        # State + integration target are visible
        assert "`planned`" in rendered
        assert "`main`" in rendered
        # Both declared paths surface verbatim
        assert "`runtime/api/domain`" in rendered
        assert "`docs/path-claims.md`" in rendered
        # Actor id is rendered
        assert f"`{actor}`" in rendered

    def test_renders_session_id_when_present(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=11003)
        target = seed_target(conn, path_string="runtime/api/domain")
        # Seed a session row so the FK on path_claims.session_id holds.
        conn.execute(
            "INSERT INTO harness_sessions (session_id, executor, provider, "
            "model, project_id, execution_lane, capabilities, workspace, mode, "
            "offered_at, last_heartbeat) "
            "VALUES ('sess-render', 'test', 'test', 'test', 1, 'primary', "
            "'[]', '/tmp', 'wait', '2026-05-01T00:00:00Z', "
            "'2026-05-01T00:00:00Z')",
        )
        conn.commit()
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id, session_id="sess-render",
        )
        rendered = render_path_claims_section(conn, item_id)
        assert "`sess-render`" in rendered

    def test_renders_blocked_claim_with_blocking_conflict(self, conn):
        actor = local_human(conn)
        item_a = _seed_item(conn, item_id=11004)
        item_b = _seed_item(conn, item_id=11005)
        target = seed_target(conn, path_string="runtime/api/domain")
        first = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_a,
        )
        activate(conn, claim_id=first, base_commit_sha=SNAP)
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_b,
            upstream_claim_id=first,
        )
        rendered = render_path_claims_section(conn, item_b)
        assert rendered is not None
        assert "`blocked`" in rendered
        assert "Current blocking conflicts" in rendered
        assert f"claim `{first}`" in rendered

    def test_renders_amendment_history(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=11006)
        target = seed_target(conn, path_string="runtime/api/domain")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        conn.execute(
            "INSERT INTO path_claim_amendments "
            "(claim_id, amendment_kind, payload, reason, amended_at) "
            "VALUES (%s, 'widen', '{}', 'follow-up scope', "
            "'2026-05-01T00:01:00Z')",
            (cid,),
        )
        conn.commit()
        rendered = render_path_claims_section(conn, item_id)
        assert rendered is not None
        assert "Amendment history" in rendered
        assert "`widen`" in rendered
        assert "follow-up scope" in rendered

    def test_renders_multiple_claims_separated_by_blank_line(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=11007)
        ta = seed_target(conn, path_string="runtime/api/domain")
        tb = seed_target(conn, path_string="docs/path-claims.md")
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[ta], item_id=item_id,
        )
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[tb], item_id=item_id,
        )
        rendered = render_path_claims_section(conn, item_id)
        assert rendered.count("### Claim") == 2

    def test_returns_none_when_table_missing(self, tmp_path):
        # A core-only DB (no path tables) simulates a minimal-fixture /
        # pre-migration environment; the renderer must fail open rather
        # than raising. Routing through the backend factory means the
        # table is genuinely absent on whichever engine runs, so the
        # production swallow fires on the matching error type (psycopg
        # UndefinedTable on Postgres, not the SQLite-only type).
        with init_test_db(
            tmp_path, apply_schema=_apply_core_only_schema
        ) as db_path:
            c = connect_test_db(db_path)
            try:
                item_id = _seed_item(c, item_id=11008)
                assert render_path_claims_section(c, item_id) is None
            finally:
                c.close()
