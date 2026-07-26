"""Move project test-command configuration into executable QA plans."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.qa_command_plan_migration import (
    COMMAND_SCOPE_POLICIES,
    migrate_registered_commands,
)
from yoke_core.domain.schema_common import _table_exists


MIGRATION_NAME = "qa_command_plan_cutover"


def apply(conn: Any) -> None:
    """Migrate every registered command and remove its legacy settings rows."""
    required = (
        "project_structure",
        "qa_methods",
        "qa_plans",
        "qa_plan_cases",
        "qa_plan_project_defaults",
        "workflows",
    )
    missing = [table for table in required if not _table_exists(conn, table)]
    if missing:
        raise RuntimeError(
            "QA command-plan cutover requires deployed tables: "
            + ", ".join(missing)
        )
    migrate_registered_commands(conn, retire_legacy=True)


def invariants(conn: Any) -> None:
    """Require zero legacy rows and well-formed migrated Command plans."""
    legacy = int(conn.execute(
        "SELECT COUNT(*) FROM project_structure "
        "WHERE family IN ('command_definitions', 'merge_verification')"
    ).fetchone()[0])
    if legacy:
        raise AssertionError(
            f"{legacy} legacy command policy rows remain after cutover"
        )
    rows = conn.execute(
        "SELECT p.slug, c.case_key, c.method_id, c.method_config "
        "FROM qa_plans p JOIN qa_plan_cases c ON c.plan_id=p.id "
        "WHERE p.slug LIKE 'registered-command-%' "
        "ORDER BY p.project_id, p.slug, c.position"
    ).fetchall()
    for row in rows:
        slug, case_key, method_id, raw_config = (
            str(row[0]), str(row[1]), str(row[2]), row[3],
        )
        scope = slug.removeprefix("registered-command-")
        try:
            config = json.loads(str(raw_config))
        except (TypeError, ValueError) as exc:
            raise AssertionError(
                f"{slug} has malformed method configuration"
            ) from exc
        if (
            scope not in COMMAND_SCOPE_POLICIES
            or case_key != scope
            or method_id != "command"
            or config.get("registered_scope") != scope
            or not str(config.get("command") or "").strip()
        ):
            raise AssertionError(
                f"{slug} does not preserve its registered command contract"
            )
    merge_rows = conn.execute(
        "SELECT c.method_id, c.method_config "
        "FROM qa_plans p JOIN qa_plan_cases c ON c.plan_id=p.id "
        "WHERE p.slug='pre-merge-verification'"
    ).fetchall()
    for row in merge_rows:
        try:
            config = json.loads(str(row[1]))
        except (TypeError, ValueError) as exc:
            raise AssertionError(
                "pre-merge verification has malformed method configuration"
            ) from exc
        if (
            str(row[0]) != "command"
            or config.get("execution_point") != "post_rebase_merge"
            or not str(config.get("command") or "").strip()
            or not isinstance(config.get("timeout_seconds"), int)
        ):
            raise AssertionError(
                "pre-merge verification does not preserve its command contract"
            )


__all__ = ["MIGRATION_NAME", "apply", "invariants"]
