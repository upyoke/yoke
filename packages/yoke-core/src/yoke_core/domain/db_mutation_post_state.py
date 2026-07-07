"""Destructive DB mutation post-state checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence, Tuple


from yoke_core.domain.schema_common import (
    _column_exists as _schema_column_exists,
    _table_exists as _schema_table_exists,
)


def _table_has_column(
    audit_conn: Any, table: str, column: str
) -> bool:
    """Return True when the authoritative DB still exposes *column*."""
    try:
        return _schema_column_exists(audit_conn, table, column)
    except Exception:
        return False


def _table_exists(audit_conn: Any, table: str) -> bool:
    """Return True when the authoritative DB still exposes *table*."""
    try:
        return _schema_table_exists(audit_conn, table)
    except Exception:
        return False


def verify_destructive_post_state(
    audit_conn: Any,
    *,
    project: str,
    profile: Mapping[str, Any],
    repo_path: Optional[Path],
    audit_path: str,
) -> List[str]:
    """Fail when a retired column or table remains on the authoritative DB."""
    from yoke_core.domain.retired_schema_registry import (
        RetiredSchemaRegistryError,
        is_retired_column,
        lookup_module,
    )
    from yoke_core.domain.retired_schema_table_registry import (
        is_retired_table,
        lookup_module_for_table,
    )

    surfaces = profile.get("affected_surfaces") or []
    if not surfaces:
        return []

    module_names: Sequence[str] = profile.get("migration_modules") or []
    module_label = ", ".join(module_names) if module_names else "<unknown>"

    try:
        retired_columns: List[Tuple[str, str, Optional[str]]] = []
        retired_tables: List[Tuple[str, Optional[str]]] = []
        for surface in surfaces:
            table = surface.get("table")
            columns = surface.get("columns") or []
            if not isinstance(table, str) or not table:
                continue
            if columns:
                for column in columns:
                    if not isinstance(column, str) or not column:
                        continue
                    if is_retired_column(
                        project, table, column, repo_root=repo_path,
                    ):
                        module = lookup_module(
                            project, table, column, repo_root=repo_path,
                        )
                        retired_columns.append((table, column, module))
            elif is_retired_table(project, table, repo_root=repo_path):
                module = lookup_module_for_table(
                    project, table, repo_root=repo_path,
                )
                retired_tables.append((table, module))
    except RetiredSchemaRegistryError as exc:
        return [
            f"retired-schema registry is malformed: {exc}. "
            "Fix runtime/api/domain/retired_schema_surfaces.yaml before re-running advance."
        ]

    offending_columns: List[Tuple[str, str, Optional[str]]] = [
        (table, column, module)
        for table, column, module in retired_columns
        if _table_has_column(audit_conn, table, column)
    ]
    offending_tables: List[Tuple[str, Optional[str]]] = [
        (table, module)
        for table, module in retired_tables
        if _table_exists(audit_conn, table)
    ]
    if not offending_columns and not offending_tables:
        return []

    bullets: List[str] = []
    for table, column, retiring_module in offending_columns:
        retiring_label = retiring_module or "(not in registry)"
        bullets.append(
            f"  - column '{table}.{column}' is still present on {audit_path}; "
            f"retired by migration module '{retiring_label}'"
        )
    for table, retiring_module in offending_tables:
        retiring_label = retiring_module or "(not in registry)"
        bullets.append(
            f"  - table '{table}' is still present on {audit_path}; "
            f"retired by migration module '{retiring_label}'"
        )

    return [
        (
            f"destructive post-state mismatch for ticket claim "
            f"(migration modules: {module_label}): the authoritative DB "
            f"still exposes surfaces the ticket claims to have retired.\n"
            f"{chr(10).join(bullets)}\n"
            f"Likely causes:\n"
            f"  * stale init/bootstrap repair logic re-added the surface "
            f"after cutover (see yoke_core.domain.projects_restart "
            f"idempotent ADD COLUMN call sites);\n"
            f"  * ambient yoke_core.cli.db_router auto-init ran schema "
            f"bootstrap on a read-looking command after the cutover.\n"
            f"Remediation: re-run the retirement against the authoritative "
            f"DB (governed runner or exception pathway), then re-run advance. "
            f"The surface must be absent on the authoritative DB before the "
            f"implementing -> reviewing-implementation transition is accepted."
        )
    ]


__all__ = ["verify_destructive_post_state"]
