"""Project-bound assembly for the server-rendered install bundle."""

from __future__ import annotations

from typing import Any, Dict, List

from yoke_contracts.project_contract.install_bundle import BUNDLE_SCHEMA
from yoke_contracts.project_contract.installed_layer import (
    installed_layer_receipt_entry,
)
from yoke_core.domain import install_bundle as bundle_sources


def _project_row(project_id: int, conn: Any) -> tuple[str, str, str]:
    """Return ``(slug, display_name, default_branch)`` for the project."""
    from yoke_core.domain import db_backend

    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT slug, name, default_branch FROM projects WHERE id = {placeholder}",
        (project_id,),
    ).fetchone()
    if row is None:
        raise bundle_sources.ProjectNotFoundError(
            f"project id {project_id} has no projects row on this env"
        )
    if hasattr(row, "keys"):
        slug, name, default_branch = row["slug"], row["name"], row["default_branch"]
    else:
        slug, name, default_branch = row[0], row[1], row[2]
    return str(slug), str(name or slug), str(default_branch or "main")


def _contract_files(display_name: str) -> List[Dict[str, str]]:
    """Return seed-if-missing project contract entries."""
    from yoke_core.domain import project_contract
    from yoke_core.domain.project_install_files import assert_safe_contract_paths

    entries = project_contract.bundle_contract_files(display_name)
    assert_safe_contract_paths(entry["path"] for entry in entries)
    return entries


def _strategy_files(
    project_id: int,
    display_name: str,
    conn: Any,
) -> List[Dict[str, str]]:
    """Return DB-rendered strategy entries, cold-starting the corpus."""
    from yoke_core.domain.project_install_strategy import (
        assert_safe_strategy_paths,
        bundle_strategy_files,
    )

    entries = bundle_strategy_files(conn, project_id, display_name)
    assert_safe_strategy_paths(entry["path"] for entry in entries)
    return entries


def build_project_bundle(project_id: int, conn: Any) -> Dict[str, Any]:
    """Render the deterministic install bundle for one project row."""
    slug, display_name, default_branch = _project_row(project_id, conn)
    from yoke_core.domain import install_bundle_managed as managed
    from yoke_core.domain.project_policy_capabilities import (
        ensure_default_policy_capabilities,
    )

    policy_capabilities = ensure_default_policy_capabilities(conn, project_id)
    conn.commit()
    root = bundle_sources.server_tree_root()
    source_engine_release = bundle_sources.yoke_version()
    files: List[Dict[str, str]] = []
    files.extend(bundle_sources._skill_files(root))
    files.extend(bundle_sources._agent_files(root))
    files.extend(bundle_sources._rules_files(root))
    files.extend(managed.docs_bundle_files(root))
    files.append(installed_layer_receipt_entry(source_engine_release))
    files.sort(key=lambda entry: entry["path"])
    return {
        "bundle_schema": BUNDLE_SCHEMA,
        "yoke_version": source_engine_release,
        "project_id": project_id,
        "project_slug": slug,
        "default_branch": default_branch,
        "files": files,
        "project_contract_files": _contract_files(display_name),
        "strategy_files": _strategy_files(project_id, display_name, conn),
        "project_policy_capabilities": policy_capabilities,
        "hooks": bundle_sources._hooks_block(),
        **managed.managed_bundle_keys(root),
    }


__all__ = ["build_project_bundle"]
