"""Migration diagnostic recipes resolve against the real ledger schema."""

from __future__ import annotations

import shlex
import sqlite3

from yoke_core.domain import schema_api_context as sac
from yoke_core.domain.migration_audit_schema import ensure_migration_audit_table
from yoke_core.domain.migration_yoke_ledger import ensure_yoke_migration_ledger
from yoke_core.domain.schema_api_context_commands_migrations import MIGRATION_COMMANDS
from yoke_core.domain.schema_api_context_render import (
    PACKET_DETAIL_FULL,
    recipe_commands,
)


def test_simulator_receives_executable_migration_reads(monkeypatch):
    monkeypatch.setattr(sac, "_try_live_schema", lambda _table: None)
    startup = sac.render_role_packet("simulator_agent")
    depth = sac.render_topic_packet(
        "core", role="simulator_agent", detail=PACKET_DETAIL_FULL
    )
    with sqlite3.connect(":memory:") as conn:
        ensure_yoke_migration_ledger(conn)
        ensure_migration_audit_table(conn)
        for name in ("OLD_NAME", "FINAL_NAME", "UNRELATED_NAME"):
            conn.execute(
                "INSERT INTO applied_migrations "
                "(migration_name, applied_at, applied_by, content_sha256) "
                "VALUES (?, '2026-01-01T00:00:00Z', 'test', 'digest')",
                (name,),
            )
        for command in recipe_commands(MIGRATION_COMMANDS[0]["recipe"]):
            assert command in startup
            assert command in depth
            argv = shlex.split(command)
            assert argv[:3] == ["yoke", "db", "read"]
            sql = argv[3].replace("PROJECT_ID", "1")
            rows = conn.execute(sql).fetchall()
            if "FROM applied_migrations" in sql:
                assert [row[0] for row in rows] == ["FINAL_NAME", "OLD_NAME"]
            else:
                assert rows == []
        for table in (
            "applied_migrations",
            "migration_audit",
            "migration_content_adoptions",
        ):
            actual = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            taught = {
                name for name, _kind in sac.seed.CANONICAL_TABLES[table]["columns"]
            }
            assert taught == actual
            assert f"**`{table}`**" in depth
